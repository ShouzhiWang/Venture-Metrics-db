import { FormEvent, useEffect, useState } from "react";
import type React from "react";
import { Search } from "lucide-react";
import {
  addProjectItem,
  createProject,
  exportProjectMarkdown,
  getCurrentUser,
  getHistoryItem,
  getProject,
  listMapItems,
  listHistory,
  listProjects,
  login,
  logout,
  register,
  removeProjectItem,
  sendChat,
  submitFeedback,
  updateProject,
  updateProjectItemNote,
  type ChatHistoryItem,
  type HistoryItem,
  type User,
} from "./api";
import { AnswerSummary } from "./components/AnswerSummary";
import { ResultSections } from "./components/ResultSections";
import { DetailDrawer, type DrawerItem } from "./components/DetailDrawer";
import { SaveToProjectButton } from "./components/SaveToProjectButton";
import type { ChatResponse, ClarifyingQuestion, MapItem, ProjectItem, ResearchProject } from "./types";

const EXAMPLES = [
  "Singapore VC deal count and median round values",
  "Compare seed vs Series A funding in Southeast Asia",
  "UK SME use of external finance",
  "Singapore digital economy share of GDP",
  "Government VC investment share in funding rounds",
  "UK small business turnover growth",
];

type Turn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
};

export function App() {
  const [path, setPath] = useState(() => normalizePath(window.location.pathname));
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);

  useEffect(() => {
    if (window.location.pathname === "/") {
      window.history.replaceState({}, "", "/data");
      setPath("/data");
    }
    function onPopState() {
      setPath(normalizePath(window.location.pathname));
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    let active = true;
    getCurrentUser()
      .then(nextUser => {
        if (active) setUser(nextUser);
      })
      .catch(() => {
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setAuthLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function navigate(nextPath: string) {
    const normalized = normalizePath(nextPath);
    window.history.pushState({}, "", normalized);
    setPath(normalized);
    window.scrollTo({ top: 0 });
  }

  return (
    <div className="page-shell">
      <TopNav path={path} user={user} onNavigate={navigate} onLogout={() => void handleLogout()} />
      {routePage(path, navigate, user, authLoading, setUser)}
    </div>
  );

  async function handleLogout() {
    await logout();
    setUser(null);
    navigate("/data");
  }
}

function DataDiscoveryPage({ onAuthRequired }: { onAuthRequired?: () => void }) {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | undefined>();
  const [drawerItem, setDrawerItem] = useState<DrawerItem | null>(null);
  const [lastQuery, setLastQuery] = useState("");
  const [answerId, setAnswerId] = useState(() => `answer-${Date.now()}`);
  const [conversationId, setConversationId] = useState<string | undefined>();

  const latestAssistant = [...turns].reverse().find(t => t.role === "assistant");
  const hasTurns = turns.length > 0;

  useEffect(() => {
    void refreshHistory();
    const stored = window.sessionStorage.getItem("projectReopenSearch");
    if (stored) {
      window.sessionStorage.removeItem("projectReopenSearch");
      try {
        const parsed = JSON.parse(stored) as { query?: string; response?: ChatResponse };
        if (parsed.response) {
          setTurns([
            { id: crypto.randomUUID(), role: "user", content: parsed.query || "Saved search" },
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: parsed.response.assistant_message || parsed.response.message,
              response: parsed.response,
            },
          ]);
          setLastQuery(parsed.query || "");
          setConversationId(parsed.response.conversation_id);
          setSelectedHistoryId(parsed.response.saved_result_id);
        }
      } catch {
        setError("Could not reopen saved project search.");
      }
    }
  }, []);

  function historyFromTurns(nextTurns = turns): ChatHistoryItem[] {
    return nextTurns
      .filter(t => t.content.trim())
      .slice(-10)
      .map(t => ({ role: t.role, content: t.content }));
  }

  async function runQuery(query: string) {
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    setLastQuery(trimmed);
    setDrawerItem(null);
    const userTurn: Turn = { id: crypto.randomUUID(), role: "user", content: trimmed };
    const nextTurns = [...turns, userTurn];
    setTurns(nextTurns);
    setMessage("");
    setLoading(true);
    setError("");
    setAnswerId(`answer-${Date.now()}`);
    try {
      const response = await sendChat(trimmed, {}, historyFromTurns(nextTurns), conversationId);
      if (response.conversation_id) {
        setConversationId(response.conversation_id);
      }
      const assistantTurn: Turn = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.assistant_message || response.message,
        response,
      };
      setTurns([...nextTurns, assistantTurn]);
      void refreshHistory();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Request failed";
      setError(msg);
      setTurns([
        ...nextTurns,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "The demo API request failed before the agent could respond.",
          response: {
            type: "error",
            message: msg,
            assistant_message: msg,
            intent: "unknown",
            clarifying_questions: [],
            tool_calls: [],
            results: {
              closest_variables: [],
              relevant_reports: [],
              relevant_organizations: [],
              source_links: [],
              comparison: {},
            },
            limitations: [msg],
          },
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void runQuery(message);
  }

  function handleChipClick(option: string) {
    const refined = lastQuery ? `${lastQuery}, ${option}` : option;
    void runQuery(refined);
  }

  async function feedback(type: string) {
    try {
      await submitFeedback(answerId, type);
    } catch {
      setError("Feedback could not be saved.");
    }
  }

  async function refreshHistory() {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      setHistoryItems(await listHistory());
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "Could not load history.");
    } finally {
      setHistoryLoading(false);
    }
  }

  async function reopenHistory(item: HistoryItem) {
    setError("");
    try {
      const fullItem = await getHistoryItem(item.id);
      if (!fullItem.result_payload) {
        setError("This history item does not include a saved result payload.");
        return;
      }
      const userTurn: Turn = {
        id: crypto.randomUUID(),
        role: "user",
        content: fullItem.query || fullItem.title,
      };
      const assistantTurn: Turn = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: fullItem.result_payload.assistant_message || fullItem.result_payload.message,
        response: fullItem.result_payload,
      };
      setTurns([userTurn, assistantTurn]);
      setLastQuery(fullItem.query || fullItem.title);
      setConversationId(fullItem.session_id || fullItem.result_payload.conversation_id);
      setSelectedHistoryId(item.id);
      setDrawerItem(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reopen history item.");
    }
  }

  function startNewSearch() {
    setTurns([]);
    setMessage("");
    setLastQuery("");
    setConversationId(undefined);
    setSelectedHistoryId(undefined);
    setDrawerItem(null);
    setError("");
  }

  const latestResponse = latestAssistant?.response;
  const isClarification = latestResponse?.type === "clarification";
  const hasResults = latestResponse && latestResponse.type !== "clarification";
  const clarifyingQuestions = latestResponse?.clarifying_questions ?? [];

  return (
    <>
      <main className="data-workspace">
        <aside className="history-sidebar" aria-label="Search history">
          <div className="history-sidebar-head">
            <h2>Searches</h2>
            <button type="button" onClick={startNewSearch}>New</button>
          </div>
          {historyLoading && <p className="history-sidebar-note">Loading...</p>}
          {historyError && <p className="history-sidebar-note error-text">{historyError}</p>}
          {!historyLoading && historyItems.length === 0 && (
            <p className="history-sidebar-note">Your saved searches will appear here.</p>
          )}
          {!historyLoading && historyItems.length > 0 && (
            <div className="history-sidebar-list">
              {historyItems.map(item => {
                const active = selectedHistoryId === item.id || Boolean(conversationId && item.session_id === conversationId);
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={active ? "active" : undefined}
                    aria-current={active ? "true" : undefined}
                    onClick={() => void reopenHistory(item)}
                  >
                    <strong>{item.query || item.title}</strong>
                    <span>{formatDate(item.created_at)}</span>
                  </button>
                );
              })}
            </div>
          )}
        </aside>

        <section className="data-main">
          <PageHeader
            title="Data That You Want"
            description="Ask for data availability, source evidence, definitions, reports, and ecosystem organizations."
          />

        {/* Search input */}
        <div className="search-area">
          <form onSubmit={onSubmit}>
            <div className="search-row">
              <Search size={17} className="search-icon" aria-hidden="true" />
              <input
                value={message}
                onChange={e => setMessage(e.target.value)}
                placeholder="Ask about a metric, geography, source, organization, or definition…"
                autoFocus
                aria-label="Search query"
              />
              <button type="submit" disabled={loading || !message.trim()}>
                {loading ? "Searching…" : "Search"}
              </button>
            </div>
          </form>

          {!hasTurns && (
            <div className="example-chips">
              {EXAMPLES.map(ex => (
                <button
                  key={ex}
                  type="button"
                  className="chip"
                  onClick={() => void runQuery(ex)}
                >
                  {ex}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Error */}
        {error && <div className="notice error">{error}</div>}

        {/* Answer area */}
        {(latestResponse || loading) && (
          <div className="result-area">
            {/* First-search loading state (no previous result yet) */}
            {loading && !latestResponse && <SearchingState />}

            {latestResponse && (
              <>
                {loading && <SearchingBanner />}
                <AnswerSummary response={latestResponse} loading={loading} />
                {hasResults && !loading && (
                  <div className="answer-actions">
                    <SaveToProjectButton
                      label="Save search to project"
                      onAuthRequired={onAuthRequired}
                      payload={{
                        item_type: "search_result",
                        item_id: latestResponse.saved_result_id,
                        title: lastQuery || latestResponse.message || "Saved search",
                        metadata: {
                          query: lastQuery,
                          answer_summary: latestResponse.assistant_message || latestResponse.message,
                          selected_variables: latestResponse.results.closest_variables,
                          relevant_reports: latestResponse.results.relevant_reports,
                          organizations: latestResponse.results.relevant_organizations,
                          source_links: latestResponse.results.source_links,
                          limitations: latestResponse.limitations,
                          result_payload: latestResponse,
                        },
                      }}
                    />
                  </div>
                )}
              </>
            )}

            {/* Clarification panel (when type === "clarification") */}
            {isClarification && clarifyingQuestions.length > 0 && (
              <ClarificationPanel
                questions={clarifyingQuestions}
                onChoose={handleChipClick}
              />
            )}

            {/* Narrow chips (when results + clarifying questions) */}
            {hasResults && clarifyingQuestions.length > 0 && (
              <NarrowChips
                questions={clarifyingQuestions}
                onChoose={handleChipClick}
              />
            )}

            {/* Result tabs */}
            {hasResults && latestResponse && (
              <ResultSections
                results={latestResponse.results}
                limitations={latestResponse.limitations}
                onViewEvidence={setDrawerItem}
                onAuthRequired={onAuthRequired}
              />
            )}

            {/* Feedback */}
            {hasResults && !loading && (
              <div className="feedback-row">
                <button type="button" onClick={() => void feedback("thumbs_up")}>
                  Useful
                </button>
                <button type="button" onClick={() => void feedback("thumbs_down")}>
                  Not useful
                </button>
              </div>
            )}
          </div>
        )}
        </section>
      </main>

      <DetailDrawer item={drawerItem} onClose={() => setDrawerItem(null)} />
    </>
  );
}

function TopNav({
  path,
  user,
  onNavigate,
  onLogout,
}: {
  path: string;
  user: User | null;
  onNavigate: (path: string) => void;
  onLogout: () => void;
}) {
  return (
    <header className="topbar">
      <a href="/data" className="site-name" onClick={event => routeClick(event, "/data", onNavigate)}>
        Startup Data Intelligence
      </a>
      <nav className="primary-nav" aria-label="Primary navigation">
        <NavLink href="/about" path={path} onNavigate={onNavigate}>About</NavLink>
        <NavLink href="/data" path={path} onNavigate={onNavigate}>Data</NavLink>
        <NavLink href="/map" path={path} onNavigate={onNavigate}>Map</NavLink>
        <NavLink href="/projects" path={path} onNavigate={onNavigate}>Projects</NavLink>
      </nav>
      <div className="auth-nav">
        {user ? (
          <div className="user-menu">
            <span>{user.name || user.email}</span>
            <button type="button" onClick={onLogout}>Logout</button>
          </div>
        ) : (
          <>
            <NavLink href="/login" path={path} onNavigate={onNavigate}>Login</NavLink>
            <a href="/register" className="register-link" onClick={event => routeClick(event, "/register", onNavigate)}>
              Register
            </a>
          </>
        )}
      </div>
    </header>
  );
}

function NavLink({
  href,
  path,
  onNavigate,
  children,
}: {
  href: string;
  path: string;
  onNavigate: (path: string) => void;
  children: React.ReactNode;
}) {
  const active = href === "/data" ? path === "/data" || path === "/" : path === href || path.startsWith(`${href}/`);
  return (
    <a
      href={href}
      className={active ? "nav-link active" : "nav-link"}
      onClick={event => routeClick(event, href, onNavigate)}
      aria-current={active ? "page" : undefined}
    >
      {children}
    </a>
  );
}

function routeClick(event: React.MouseEvent<HTMLAnchorElement>, href: string, onNavigate: (path: string) => void) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
  event.preventDefault();
  onNavigate(href);
}

function routePage(
  path: string,
  navigate: (path: string) => void,
  user: User | null,
  authLoading: boolean,
  setUser: (user: User | null) => void,
) {
  if (path === "/about") return <AboutPage />;
  if (path === "/data" || path === "/") {
    return (
      <ProtectedPage user={user} authLoading={authLoading} navigate={navigate}>
        <DataDiscoveryPage onAuthRequired={() => navigate("/login")} />
      </ProtectedPage>
    );
  }
  if (path === "/login") return <AuthPage mode="login" user={user} onAuthed={nextUser => { setUser(nextUser); navigate("/data"); }} />;
  if (path === "/register") return <AuthPage mode="register" user={user} onAuthed={nextUser => { setUser(nextUser); navigate("/data"); }} />;
  if (path === "/projects") return <ProtectedPage user={user} authLoading={authLoading} navigate={navigate}><ProjectsPage onNavigate={navigate} /></ProtectedPage>;
  if (path.startsWith("/projects/")) {
    return (
      <ProtectedPage user={user} authLoading={authLoading} navigate={navigate}>
        <ProjectDetailPage projectId={decodeURIComponent(path.replace("/projects/", ""))} onNavigate={navigate} />
      </ProtectedPage>
    );
  }
  if (path === "/map") return <MapPage />;
  return <NotFoundPage onNavigate={navigate} />;
}

function normalizePath(value: string) {
  if (!value || value === "/") return "/";
  return value.endsWith("/") && value.length > 1 ? value.slice(0, -1) : value;
}

function PageHeader({ title, description }: { title: string; description: string }) {
  return (
    <section className="page-header">
      <h1>{title}</h1>
      <p>{description}</p>
    </section>
  );
}

function AboutPage() {
  return (
    <main className="main-content about-content">
      <section className="about-hero">
        <h1>Startup Data Intelligence for Asian Markets</h1>
        <p>Find startup, funding, innovation, and ecosystem data with definitions, sources, and evidence.</p>
      </section>

      <div className="about-grid">
        <InfoCard
          title="The Problem"
          items={[
            "Startup and innovation data is fragmented across reports, government sources, private databases, and organization websites.",
            "Similar concepts are often defined differently across reports.",
            "Public and private data sources are often mixed together.",
            "Asian startup ecosystems need better structured, comparable data.",
          ]}
        />
        <InfoCard
          title="What This Platform Does"
          items={[
            "Finds relevant variables, reports, datasets, and organizations.",
            "Shows definitions and measurement methods.",
            "Labels data availability as obtainable, private, unclear, or not obtainable.",
            "Provides evidence quotes and source links.",
            "Helps compare concepts across reports.",
          ]}
        />
      </div>

      <section className="content-section">
        <h2>How It Works</h2>
        <PipelineDiagram />
      </section>

      <section className="content-section">
        <h2>Data Availability Labels</h2>
        <div className="availability-list">
          <AvailabilityExplainer label="Obtainable" description="Public or downloadable source." />
          <AvailabilityExplainer label="Private" description="Underlying data comes from proprietary databases." />
          <AvailabilityExplainer label="Unclear" description="Source is not clearly stated." />
          <AvailabilityExplainer label="Not obtainable" description="Estimate, proprietary, or closed source." />
        </div>
      </section>

      <InfoCard
        title="Current Limitations"
        items={[
          "Database is still growing.",
          "Some regions and sectors are under-covered.",
          "Some sources are gated or private.",
          "Extracted variables remain reviewable, not automatically authoritative.",
        ]}
      />
    </main>
  );
}

function InfoCard({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="content-section">
      <h2>{title}</h2>
      <ul className="about-list">
        {items.map(item => <li key={item}>{item}</li>)}
      </ul>
    </section>
  );
}

function PipelineDiagram() {
  const steps = ["Sources", "Reports", "Codebooks", "Search Index", "Data Discovery Assistant"];
  return (
    <ol className="pipeline-diagram" aria-label="Data processing pipeline">
      {steps.map(step => <li key={step}>{step}</li>)}
    </ol>
  );
}

function AvailabilityExplainer({ label, description }: { label: string; description: string }) {
  return (
    <div className="availability-row">
      <strong>{label}</strong>
      <p>{description}</p>
    </div>
  );
}

function AuthPage({ mode, user, onAuthed }: { mode: "login" | "register"; user: User | null; onAuthed: (user: User) => void }) {
  const isLogin = mode === "login";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const nextUser = isLogin
        ? await login(email, password)
        : await register(name, email, password);
      onAuthed(nextUser);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (user) {
    return (
      <main className="main-content narrow-content">
        <PageHeader title={isLogin ? "Login" : "Register"} description="You are already logged in." />
        <p className="muted-copy">Use the navigation bar to continue, or log out from the user menu.</p>
      </main>
    );
  }

  return (
    <main className="main-content narrow-content">
      <PageHeader
        title={isLogin ? "Login" : "Register"}
        description={isLogin ? "Log in to access query history and research projects." : "Create an account to save history and research projects later."}
      />
      <form className="auth-form" onSubmit={onSubmit}>
        {!isLogin && (
          <label>
            Name
            <input
              value={name}
              onChange={event => setName(event.target.value)}
              placeholder="Your name"
              autoComplete="name"
              required
            />
          </label>
        )}
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={event => setEmail(event.target.value)}
            placeholder="name@example.com"
            autoComplete="email"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={event => setPassword(event.target.value)}
            placeholder="Password"
            autoComplete={isLogin ? "current-password" : "new-password"}
            minLength={isLogin ? 1 : 8}
            required
          />
        </label>
        {error && <p className="form-error">{error}</p>}
        <button type="submit" disabled={submitting}>{submitting ? "Working..." : isLogin ? "Login" : "Register"}</button>
      </form>
      <p className="muted-copy">
        {isLogin ? "No account yet? Use Register in the navigation bar." : "Already have an account? Use Login in the navigation bar."}
      </p>
    </main>
  );
}

function ProtectedPage({
  user,
  authLoading,
  navigate,
  children,
}: {
  user: User | null;
  authLoading: boolean;
  navigate: (path: string) => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!authLoading && !user) {
      navigate("/login");
    }
  }, [authLoading, user, navigate]);

  if (authLoading) {
    return <PlaceholderPage title="Checking session" description="Confirming your login status." />;
  }
  if (!user) {
    return <PlaceholderPage title="Login required" description="Redirecting to login." />;
  }
  return <>{children}</>;
}

function ProjectsPage({ onNavigate }: { onNavigate: (path: string) => void }) {
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [title, setTitle] = useState("");
  const [researchQuestion, setResearchQuestion] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    listProjects()
      .then(items => {
        if (active) setProjects(items);
      })
      .catch(err => {
        if (active) setError(err instanceof Error ? err.message : "Could not load projects.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const project = await createProject({ title, description, research_question: researchQuestion });
      setProjects([project, ...projects]);
      setTitle("");
      setResearchQuestion("");
      setDescription("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create project.");
    }
  }

  return (
    <main className="main-content">
      <PageHeader
        title="Research Projects"
        description="Group searches, source notes, and selected variables into project workspaces."
      />
      {error && <div className="notice error">{error}</div>}
      <section className="content-section">
        <h2>Create Project</h2>
        <form className="project-form" onSubmit={submit}>
          <label>Title<input value={title} onChange={event => setTitle(event.target.value)} required /></label>
          <label>Research question<input value={researchQuestion} onChange={event => setResearchQuestion(event.target.value)} /></label>
          <label>Description<textarea value={description} onChange={event => setDescription(event.target.value)} rows={3} /></label>
          <button type="submit">Create project</button>
        </form>
      </section>
      <section className="content-section">
        <h2>Your Projects</h2>
        {loading && <p className="muted-copy">Loading projects...</p>}
        {!loading && projects.length === 0 && <p className="muted-copy">No projects yet.</p>}
        <div className="project-list">
          {projects.map(project => (
            <button key={project.id} type="button" onClick={() => onNavigate(`/projects/${project.id}`)}>
              <strong>{project.title}</strong>
              {project.research_question && <span>{project.research_question}</span>}
              <small>{project.item_count || 0} saved items · updated {formatDate(project.updated_at)}</small>
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}

function ProjectDetailPage({ projectId, onNavigate }: { projectId: string; onNavigate: (path: string) => void }) {
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [items, setItems] = useState<ProjectItem[]>([]);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [researchQuestion, setResearchQuestion] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [markdown, setMarkdown] = useState("");

  useEffect(() => {
    void loadProject();
  }, [projectId]);

  async function loadProject() {
    setError("");
    try {
      const result = await getProject(projectId);
      setProject(result.project);
      setItems(result.items);
      setTitle(result.project.title);
      setDescription(result.project.description || "");
      setResearchQuestion(result.project.research_question || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load project.");
    }
  }

  async function saveProject(event: FormEvent) {
    event.preventDefault();
    try {
      const next = await updateProject(projectId, { title, description, research_question: researchQuestion });
      setProject(next);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update project.");
    }
  }

  async function addNote(event: FormEvent) {
    event.preventDefault();
    if (!note.trim()) return;
    try {
      await addProjectItem(projectId, { item_type: "note", title: note.trim().slice(0, 80), note, metadata: {} });
      setNote("");
      await loadProject();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add note.");
    }
  }

  async function saveItemNote(itemId: string, nextNote: string) {
    try {
      await updateProjectItemNote(itemId, nextNote);
      await loadProject();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update note.");
    }
  }

  async function removeItem(itemId: string) {
    try {
      await removeProjectItem(itemId);
      setItems(items.filter(item => item.id !== itemId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove item.");
    }
  }

  async function exportMarkdown() {
    try {
      setMarkdown(await exportProjectMarkdown(projectId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not export project.");
    }
  }

  function reopenSearch(item: ProjectItem) {
    const payload = item.metadata?.result_payload;
    if (payload && typeof payload === "object") {
      window.sessionStorage.setItem("projectReopenSearch", JSON.stringify({ query: item.metadata?.query, response: payload }));
    }
    onNavigate("/data");
  }

  const grouped = groupProjectItems(items);

  return (
    <main className="main-content">
      <PageHeader title={project?.title || "Project"} description={project?.research_question || "Research workspace."} />
      {error && <div className="notice error">{error}</div>}
      {!project && !error && <p className="muted-copy">Loading project...</p>}
      {project && (
        <>
          <div className="project-toolbar">
            <button type="button" onClick={() => setEditing(!editing)}>{editing ? "Cancel edit" : "Edit project"}</button>
            <button type="button" onClick={() => void exportMarkdown()}>Export markdown</button>
          </div>
          {editing && (
            <section className="content-section">
              <form className="project-form" onSubmit={saveProject}>
                <label>Title<input value={title} onChange={event => setTitle(event.target.value)} required /></label>
                <label>Research question<input value={researchQuestion} onChange={event => setResearchQuestion(event.target.value)} /></label>
                <label>Description<textarea value={description} onChange={event => setDescription(event.target.value)} rows={3} /></label>
                <button type="submit">Save changes</button>
              </form>
            </section>
          )}
          {project.description && (
            <section className="content-section">
              <h2>Description</h2>
              <p>{project.description}</p>
            </section>
          )}
          <form className="project-note-form" onSubmit={addNote}>
            <label>
              Notes
              <textarea value={note} onChange={event => setNote(event.target.value)} rows={3} placeholder="Add a note to this project" />
            </label>
            <button type="submit">Add note</button>
          </form>
          {(["search_result", "variable", "report", "source", "organization", "note"] as ProjectItem["item_type"][]).map(type => (
            <ProjectItemSection
              key={type}
              title={projectSectionTitle(type)}
              items={grouped[type] || []}
              onRemove={removeItem}
              onSaveNote={saveItemNote}
              onReopen={type === "search_result" ? reopenSearch : undefined}
            />
          ))}
          {markdown && (
            <section className="content-section">
              <h2>Markdown Export</h2>
              <textarea className="markdown-export" value={markdown} readOnly rows={12} />
            </section>
          )}
        </>
      )}
    </main>
  );
}

function ProjectItemSection({
  title,
  items,
  onRemove,
  onSaveNote,
  onReopen,
}: {
  title: string;
  items: ProjectItem[];
  onRemove: (itemId: string) => void;
  onSaveNote: (itemId: string, note: string) => void;
  onReopen?: (item: ProjectItem) => void;
}) {
  if (items.length === 0) return null;
  return (
    <section className="content-section">
      <h2>{title}</h2>
      <div className="project-items">
        {items.map(item => (
          <ProjectItemCard key={item.id} item={item} onRemove={onRemove} onSaveNote={onSaveNote} onReopen={onReopen} />
        ))}
      </div>
    </section>
  );
}

function ProjectItemCard({
  item,
  onRemove,
  onSaveNote,
  onReopen,
}: {
  item: ProjectItem;
  onRemove: (itemId: string) => void;
  onSaveNote: (itemId: string, note: string) => void;
  onReopen?: (item: ProjectItem) => void;
}) {
  const [note, setNote] = useState(item.note || "");
  const sourceUrl = stringFromMetadata(item.metadata, "source_url");
  return (
    <article className="project-item-card">
      <div>
        <h3>{item.title || item.item_type}</h3>
        <p>{item.item_type}</p>
        {sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">Open source</a>}
      </div>
      <label>
        Note
        <textarea value={note} onChange={event => setNote(event.target.value)} rows={2} />
      </label>
      <div className="project-item-actions">
        {onReopen && <button type="button" onClick={() => onReopen(item)}>Reopen</button>}
        <button type="button" onClick={() => onSaveNote(item.id, note)}>Save note</button>
        <button type="button" onClick={() => onRemove(item.id)}>Remove</button>
      </div>
    </article>
  );
}

function groupProjectItems(items: ProjectItem[]) {
  return items.reduce<Record<string, ProjectItem[]>>((acc, item) => {
    acc[item.item_type] = [...(acc[item.item_type] || []), item];
    return acc;
  }, {});
}

function projectSectionTitle(type: ProjectItem["item_type"]) {
  const labels: Record<string, string> = {
    search_result: "Saved Searches",
    variable: "Saved Variables",
    report: "Saved Reports",
    source: "Saved Sources",
    organization: "Saved Organizations",
    note: "Notes",
  };
  return labels[type] || type;
}

function stringFromMetadata(metadata: Record<string, unknown>, key: string) {
  const direct = metadata[key];
  if (typeof direct === "string") return direct;
  for (const value of Object.values(metadata)) {
    if (value && typeof value === "object" && key in value && typeof (value as Record<string, unknown>)[key] === "string") {
      return String((value as Record<string, unknown>)[key]);
    }
  }
  return "";
}

function MapPage() {
  const [items, setItems] = useState<MapItem[]>([]);
  const [selected, setSelected] = useState<MapItem | null>(null);
  const [country, setCountry] = useState("");
  const [type, setType] = useState("");
  const [availability, setAvailability] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    listMapItems()
      .then(setItems)
      .catch(err => setError(err instanceof Error ? err.message : "Could not load map items."));
  }, []);

  const countries = unique(items.map(item => item.country).filter(Boolean) as string[]);
  const filtered = items.filter(item => {
    if (country && item.country !== country) return false;
    if (type && item.type !== type) return false;
    if (availability && (item.availability || "unclear") !== availability) return false;
    return true;
  });

  return (
    <main className="map-page">
      <section className="map-sidebar">
        <h1>Dynamic Map</h1>
        <p>Explore geographies with available reports, variables, sources, and organizations.</p>
        {error && <div className="notice error">{error}</div>}
        <label>Country<select value={country} onChange={event => setCountry(event.target.value)}><option value="">All</option>{countries.map(item => <option key={item}>{item}</option>)}</select></label>
        <label>Type<select value={type} onChange={event => setType(event.target.value)}><option value="">All</option><option value="organization">Organizations</option><option value="report">Reports</option><option value="variable">Variables</option><option value="source">Sources</option></select></label>
        <label>Availability<select value={availability} onChange={event => setAvailability(event.target.value)}><option value="">All</option>{unique(items.map(item => item.availability || "unclear")).map(item => <option key={item}>{item}</option>)}</select></label>
        {selected && (
          <div className="map-detail">
            <h2>{selected.city || selected.country || selected.title}</h2>
            <p>{selected.title}</p>
            {selected.description && <p>{selected.description}</p>}
            <dl>
              <dt>Type</dt><dd>{selected.type}</dd>
              <dt>Country</dt><dd>{selected.country || "Unknown"}</dd>
              <dt>Availability</dt><dd>{selected.availability || "unclear"}</dd>
            </dl>
          </div>
        )}
      </section>
      <section className="map-canvas" aria-label="Asia map">
        {filtered.map(item => {
          const pos = mapPosition(item);
          return (
            <button
              key={`${item.type}-${item.id}`}
              type="button"
              className={`map-marker ${item.type}`}
              style={{ left: `${pos.x}%`, top: `${pos.y}%` }}
              title={item.title}
              onClick={() => setSelected(item)}
            >
              <span>{item.type[0].toUpperCase()}</span>
            </button>
          );
        })}
        <div className="map-empty">{filtered.length === 0 ? "No mapped items for these filters." : `${filtered.length} mapped items`}</div>
      </section>
    </main>
  );
}

function unique(values: string[]) {
  return [...new Set(values.filter(Boolean))].sort();
}

function mapPosition(item: MapItem) {
  const minLng = 65;
  const maxLng = 150;
  const minLat = -12;
  const maxLat = 48;
  return {
    x: Math.min(96, Math.max(4, ((item.lng - minLng) / (maxLng - minLng)) * 100)),
    y: Math.min(96, Math.max(4, 100 - ((item.lat - minLat) / (maxLat - minLat)) * 100)),
  };
}

function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return (
    <main className="main-content narrow-content">
      <PageHeader title={title} description={description} />
      <section className="content-section">
        <h2>Status</h2>
        <p>This page is part of the MVP navigation structure. Backend data and protected account features are not connected yet.</p>
      </section>
    </main>
  );
}

function NotFoundPage({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <main className="main-content narrow-content">
      <PageHeader title="Page not found" description="The requested page does not exist in the MVP demo." />
      <button type="button" className="plain-action" onClick={() => onNavigate("/data")}>Go to Data</button>
    </main>
  );
}

function formatDate(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const SEARCH_STEPS = [
  "Analyzing your query…",
  "Searching variable database…",
  "Matching relevant reports…",
  "Finding organizations…",
  "Compiling results…",
];

function SearchingState() {
  return (
    <div className="searching-state">
      <div className="searching-spinner" aria-hidden="true" />
      <div className="searching-steps">
        {SEARCH_STEPS.map((step, i) => (
          <span key={step} className="searching-step" style={{ animationDelay: `${i * 0.55}s` }}>
            {step}
          </span>
        ))}
      </div>
    </div>
  );
}

function SearchingBanner() {
  return (
    <div className="searching-banner" aria-live="polite">
      <div className="searching-spinner small" aria-hidden="true" />
      <span>Searching…</span>
    </div>
  );
}

function ClarificationPanel({
  questions,
  onChoose,
}: {
  questions: ClarifyingQuestion[];
  onChoose: (option: string) => void;
}) {
  return (
    <div className="clarification-panel">
      <p>Could you clarify what you&rsquo;re looking for?</p>
      {questions.map(q => (
        <div className="clarification-question" key={q.question}>
          <p>{q.question}</p>
          {q.options && q.options.length > 0 && (
            <div className="example-chips">
              {q.options.map(opt => (
                <button
                  key={opt}
                  type="button"
                  className="chip"
                  onClick={() => onChoose(opt)}
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function NarrowChips({
  questions,
  onChoose,
}: {
  questions: ClarifyingQuestion[];
  onChoose: (option: string) => void;
}) {
  const allOptions = questions.flatMap(q => q.options ?? []);
  if (allOptions.length === 0) return null;

  return (
    <div className="narrow-section">
      <span className="narrow-label">Narrow your search:</span>
      {allOptions.map(opt => (
        <button
          key={opt}
          type="button"
          className="chip"
          onClick={() => onChoose(opt)}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}
