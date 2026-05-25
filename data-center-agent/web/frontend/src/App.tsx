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
  queryProject,
  register,
  removeProjectItem,
  sendChat,
  submitFeedback,
  updateProject,
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
  "India startup ecosystem funding by stage",
];

const ABOUT_EXAMPLES = [
  "Singapore VC deal count 2020–2023",
  "Southeast Asia fintech ecosystem organizations",
  "India startup funding by sector",
  "UK SME bank loan usage rates",
  "Government innovation fund data, Southeast Asia",
  "China unicorn company count and valuation",
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
      <SiteFooter />
    </div>
  );

  async function handleLogout() {
    await logout();
    setUser(null);
    navigate("/data");
  }
}

function SiteFooter() {
  return (
    <footer className="site-footer">
      Prototype database — results are evidence-backed but still under review.
    </footer>
  );
}

function DataDiscoveryPage({
  onAuthRequired,
  onNavigate,
}: {
  onAuthRequired?: () => void;
  onNavigate?: (path: string) => void;
}) {
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
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [savedResultIds, setSavedResultIds] = useState<Set<string>>(new Set());

  const latestAssistant = [...turns].reverse().find(t => t.role === "assistant");
  const hasTurns = turns.length > 0;

  useEffect(() => {
    void refreshHistory();
    void refreshProjects();

    // Check if an example query was passed from the About page
    const aboutQuery = window.sessionStorage.getItem("aboutExampleQuery");
    if (aboutQuery) {
      window.sessionStorage.removeItem("aboutExampleQuery");
      void runQuery(aboutQuery);
      return;
    }

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
        setError("Could not reopen the saved search.");
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
          content: "The search could not complete. Please try again.",
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
            limitations: [],
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
      // Feedback failure is non-critical
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

  async function refreshProjects() {
    setProjectsLoading(true);
    try {
      setProjects(await listProjects());
    } catch {
      // Projects section silently fails if not logged in
    } finally {
      setProjectsLoading(false);
    }
  }

  function handleSaved() {
    const savedId = latestResponse?.saved_result_id;
    if (savedId) {
      setSavedResultIds(prev => new Set([...prev, savedId]));
    }
    void refreshProjects();
    void refreshHistory();
  }

  async function reopenHistory(item: HistoryItem) {
    setError("");
    try {
      const fullItem = await getHistoryItem(item.id);
      if (!fullItem.result_payload) {
        setError("This search doesn't have a saved result. Try running it again.");
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
      setError(err instanceof Error ? err.message : "Could not load this search.");
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

  // Filter out searches that have been saved to a project this session
  const visibleHistory = historyItems.filter(item => !savedResultIds.has(item.id));

  return (
    <>
      <main className="data-workspace">
        <aside className="history-sidebar" aria-label="Research sidebar">
          {/* Projects section at top */}
          <div className="sidebar-section">
            <div className="sidebar-section-head">
              <span className="sidebar-section-label">Projects</span>
              {onNavigate && (
                <button type="button" onClick={() => onNavigate("/projects")}>Manage</button>
              )}
            </div>
            {projectsLoading && <p className="sidebar-note">Loading…</p>}
            {!projectsLoading && projects.length === 0 && (
              <p className="sidebar-note">Save a search to start a project.</p>
            )}
            {!projectsLoading && projects.length > 0 && (
              <div className="sidebar-list">
                {projects.map(p => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => onNavigate?.(`/projects/${p.id}`)}
                  >
                    <strong>{p.title}</strong>
                    <span>{p.item_count || 0} item{(p.item_count || 0) !== 1 ? "s" : ""}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Searches section at bottom */}
          <div className="sidebar-section sidebar-section-fill">
            <div className="sidebar-section-head">
              <span className="sidebar-section-label">Searches</span>
              <button type="button" onClick={startNewSearch}>New</button>
            </div>
            {historyLoading && <p className="sidebar-note">Loading…</p>}
            {historyError && <p className="sidebar-note error-text">{historyError}</p>}
            {!historyLoading && visibleHistory.length === 0 && (
              <p className="sidebar-note">Your recent searches appear here.</p>
            )}
            {!historyLoading && visibleHistory.length > 0 && (
              <div className="sidebar-list">
                {visibleHistory.map(item => {
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
          </div>
        </aside>

        <section className="data-main">
          <PageHeader
            title="Find Startup & Innovation Data"
            description="Search for metrics, reports, organizations, and source evidence across Asian markets."
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
          {error && (
            <div className="notice error" role="alert">
              {error}
            </div>
          )}

          {/* Answer area */}
          {(latestResponse || loading) && (
            <div className="result-area">
              {loading && !latestResponse && <SearchingState />}

              {latestResponse && (
                <>
                  {loading && <SearchingBanner />}
                  <AnswerSummary response={latestResponse} loading={loading} />
                  {hasResults && !loading && (
                    <div className="answer-actions">
                      <SaveToProjectButton
                        label="Save to project"
                        onAuthRequired={onAuthRequired}
                        onSaved={handleSaved}
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

              {isClarification && clarifyingQuestions.length > 0 && (
                <ClarificationPanel
                  questions={clarifyingQuestions}
                  onChoose={handleChipClick}
                />
              )}

              {hasResults && clarifyingQuestions.length > 0 && (
                <NarrowChips
                  questions={clarifyingQuestions}
                  onChoose={handleChipClick}
                />
              )}

              {hasResults && latestResponse && (
                <ResultSections
                  results={latestResponse.results}
                  limitations={latestResponse.limitations}
                  onViewEvidence={setDrawerItem}
                  onAuthRequired={onAuthRequired}
                />
              )}

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
        Venture Metrics
      </a>
      <nav className="primary-nav" aria-label="Primary navigation">
        <NavLink href="/data" path={path} onNavigate={onNavigate}>Data</NavLink>
        <NavLink href="/map" path={path} onNavigate={onNavigate}>Map</NavLink>
        <NavLink href="/projects" path={path} onNavigate={onNavigate}>Projects</NavLink>
        <NavLink href="/about" path={path} onNavigate={onNavigate}>About</NavLink>
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
  if (path === "/about") return <AboutPage onNavigate={navigate} />;
  if (path === "/data" || path === "/") {
    return (
      <ProtectedPage user={user} authLoading={authLoading} navigate={navigate}>
        <DataDiscoveryPage
          onAuthRequired={() => navigate("/login")}
          onNavigate={navigate}
        />
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

function AboutPage({ onNavigate }: { onNavigate: (path: string) => void }) {
  function runExample(query: string) {
    window.sessionStorage.setItem("aboutExampleQuery", query);
    onNavigate("/data");
  }

  return (
    <main className="main-content about-content">
      <div className="about-intro">
        <h1>Startup &amp; Innovation Data Intelligence</h1>
        <p>
          Find structured data on VC funding, startup ecosystems, SME finance, and innovation metrics across Asian markets.
          Every result includes source evidence, availability labels, and definition context.
        </p>
        <div className="about-cta-row">
          <a
            href="/data"
            className="about-cta-btn"
            onClick={event => routeClick(event, "/data", onNavigate)}
          >
            Search the database
          </a>
        </div>
      </div>

      <div className="about-capabilities">
        <div className="capability-card">
          <h3>Source evidence</h3>
          <p>Every data point links back to its source report, dataset, or organization. No unattributed claims.</p>
        </div>
        <div className="capability-card">
          <h3>Availability labels</h3>
          <p>Variables are labeled obtainable, private, unclear, or not obtainable — so you know what you can access.</p>
        </div>
        <div className="capability-card">
          <h3>Definition context</h3>
          <p>Metrics come with how they're defined and measured, enabling cross-source comparisons.</p>
        </div>
        <div className="capability-card">
          <h3>Research projects</h3>
          <p>Save searches, variables, and reports into project workspaces for longer-form research.</p>
        </div>
      </div>

      <section className="content-section">
        <h2>Example searches</h2>
        <p className="section-subtext">Click any query to run it.</p>
        <div className="example-chips" style={{ marginTop: "8px" }}>
          {ABOUT_EXAMPLES.map(ex => (
            <button
              key={ex}
              type="button"
              className="chip"
              onClick={() => runExample(ex)}
            >
              {ex}
            </button>
          ))}
        </div>
      </section>

      <section className="content-section">
        <h2>Data availability labels</h2>
        <div className="availability-legend">
          <div className="availability-legend-item">
            <span className="availability public">Obtainable</span>
            <span>Public or downloadable source</span>
          </div>
          <div className="availability-legend-item">
            <span className="availability private">Private</span>
            <span>Underlying data is proprietary</span>
          </div>
          <div className="availability-legend-item">
            <span className="availability unclear">Unclear</span>
            <span>Source is not clearly stated</span>
          </div>
          <div className="availability-legend-item">
            <span className="availability none">Not obtainable</span>
            <span>Estimate, proprietary, or closed source</span>
          </div>
        </div>
      </section>

      <section className="content-section">
        <h2>How it works</h2>
        <PipelineDiagram />
      </section>

      <section className="content-section">
        <h2>Current coverage</h2>
        <div className="about-coverage">
          <div className="coverage-item">
            <strong>Focus markets</strong>
            <span>Singapore, India, Southeast Asia, UK, China</span>
          </div>
          <div className="coverage-item">
            <strong>Data types</strong>
            <span>VC funding, startup counts, SME finance, innovation indices, ecosystem organizations</span>
          </div>
          <div className="coverage-item">
            <strong>Sources</strong>
            <span>Government statistics, research reports, industry databases, academic publications</span>
          </div>
        </div>
        <p className="about-limitation">
          The database is still growing. Some regions and sectors are under-covered, and some sources are gated or private.
          Extracted variables remain reviewable — treat results as a starting point, not a final authority.
        </p>
      </section>
    </main>
  );
}

function PipelineDiagram() {
  const steps = ["Sources", "Reports", "Codebooks", "Search Index", "Data Discovery"];
  return (
    <ol className="pipeline-diagram" aria-label="Data processing pipeline">
      {steps.map(step => <li key={step}>{step}</li>)}
    </ol>
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
      setError(err instanceof Error ? err.message : "Authentication failed. Please check your credentials.");
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
        title={isLogin ? "Login" : "Create account"}
        description={isLogin ? "Access your query history and research projects." : "Save searches and organize findings into research projects."}
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
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>{submitting ? "Working…" : isLogin ? "Login" : "Create account"}</button>
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
        description="Organize searches, variables, and source notes into project workspaces."
      />
      {error && <div className="notice error" role="alert">{error}</div>}
      <section className="content-section">
        <h2>New project</h2>
        <form className="project-form" onSubmit={submit}>
          <label>Title<input value={title} onChange={event => setTitle(event.target.value)} required /></label>
          <label>Research question<input value={researchQuestion} onChange={event => setResearchQuestion(event.target.value)} /></label>
          <label>Description<textarea value={description} onChange={event => setDescription(event.target.value)} rows={3} /></label>
          <button type="submit">Create project</button>
        </form>
      </section>
      <section className="content-section">
        <h2>Your projects</h2>
        {loading && <p className="muted-copy">Loading…</p>}
        {!loading && projects.length === 0 && (
          <p className="muted-copy">No projects yet. Save a search from the Data page to create one.</p>
        )}
        <div className="project-list">
          {projects.map(project => (
            <button key={project.id} type="button" onClick={() => onNavigate(`/projects/${project.id}`)}>
              <strong>{project.title}</strong>
              {project.research_question && <span>{project.research_question}</span>}
              <small>{project.item_count || 0} saved item{(project.item_count || 0) !== 1 ? "s" : ""} · updated {formatDate(project.updated_at)}</small>
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}

// ── Project workspace helpers ──────────────────

function generateSuggestedQueries(project: ResearchProject): string[] {
  const title = (project.title || "").trim();
  const question = (project.research_question || "").trim();
  if (!title) return [];
  const topic = title.replace(/\b(research|project|study|analysis|overview|report)\b/gi, "").trim() || title;
  const queries: string[] = [];
  if (question && question.length < 90) queries.push(question);
  queries.push(
    `${topic} startup funding by stage`,
    `${topic} VC deal count trends`,
    `${topic} innovation and digital economy metrics`,
    `Startup ecosystem organizations in ${topic}`,
    `Compare funding definitions for ${topic}`,
  );
  return [...new Set(queries)].filter(q => q.length > 10 && q.length < 120).slice(0, 5);
}

function projectItemToDrawerItem(item: ProjectItem): import("./components/DetailDrawer").DrawerItem | null {
  const meta = item.metadata;
  if (!meta) return null;
  if (item.item_type === "variable" && meta.variable) return { kind: "variable", data: meta.variable as never };
  if (item.item_type === "report" && meta.report) return { kind: "report", data: meta.report as never };
  if (item.item_type === "organization" && meta.organization) return { kind: "organization", data: meta.organization as never };
  if (item.item_type === "source" && meta.source) return { kind: "source", data: meta.source as never };
  return null;
}

function evidenceTypeLabel(type: ProjectItem["item_type"]): string {
  const map: Record<string, string> = {
    variable: "Var", report: "Rep", organization: "Org",
    source: "Src", search_result: "Search", note: "Note",
  };
  return map[type] || type;
}

function groupProjectItems(items: ProjectItem[]) {
  return items.reduce<Record<string, ProjectItem[]>>((acc, item) => {
    acc[item.item_type] = [...(acc[item.item_type] || []), item];
    return acc;
  }, {});
}

// ── Project workspace ─────────────────────────

function ProjectDetailPage({ projectId, onNavigate }: { projectId: string; onNavigate: (path: string) => void }) {
  // Project data
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [items, setItems] = useState<ProjectItem[]>([]);
  const [loadError, setLoadError] = useState("");

  // Edit state
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editQuestion, setEditQuestion] = useState("");
  const [editDescription, setEditDescription] = useState("");

  // Chat state
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [lastQuery, setLastQuery] = useState("");
  const [answerId, setAnswerId] = useState(() => `answer-${Date.now()}`);
  const [hasQueried, setHasQueried] = useState(false);

  // UI state
  const [drawerItem, setDrawerItem] = useState<DrawerItem | null>(null);
  const [noteText, setNoteText] = useState("");
  const [sidebarTab, setSidebarTab] = useState<"evidence" | "notes">("evidence");
  const [markdown, setMarkdown] = useState("");
  const [showMarkdown, setShowMarkdown] = useState(false);

  const latestAssistant = [...turns].reverse().find(t => t.role === "assistant");
  const latestResponse = latestAssistant?.response;
  const isClarification = latestResponse?.type === "clarification";
  const hasResults = latestResponse && latestResponse.type !== "clarification";
  const clarifyingQuestions = latestResponse?.clarifying_questions ?? [];

  const grouped = groupProjectItems(items);
  const evidenceItems = items.filter(i => i.item_type !== "note");
  const noteItems = grouped.note || [];
  const stats = {
    searches: (grouped.search_result || []).length,
    variables: (grouped.variable || []).length,
    reports: (grouped.report || []).length,
    sources: (grouped.source || []).length + (grouped.organization || []).length,
    notes: noteItems.length,
  };

  useEffect(() => { void loadProject(); }, [projectId]);

  async function loadProject() {
    setLoadError("");
    try {
      const result = await getProject(projectId);
      setProject(result.project);
      setItems(result.items);
      setEditTitle(result.project.title);
      setEditQuestion(result.project.research_question || "");
      setEditDescription(result.project.description || "");
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load this project.");
    }
  }

  function historyFromTurns(): ChatHistoryItem[] {
    return turns.filter(t => t.content.trim()).slice(-10).map(t => ({ role: t.role, content: t.content }));
  }

  async function runProjectQuery(query: string) {
    const trimmed = query.trim();
    if (!trimmed || chatLoading) return;
    setLastQuery(trimmed);
    setDrawerItem(null);
    setChatLoading(true);
    setChatError("");
    setHasQueried(true);
    setAnswerId(`answer-${Date.now()}`);
    const userTurn: Turn = { id: crypto.randomUUID(), role: "user", content: trimmed };
    const nextTurns = [...turns, userTurn];
    setTurns(nextTurns);
    setMessage("");
    try {
      const response = await queryProject(projectId, trimmed, historyFromTurns(), conversationId);
      if (response.conversation_id) setConversationId(response.conversation_id);
      setTurns([...nextTurns, {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.assistant_message || response.message,
        response,
      }]);
      // Auto-save every successful search to the project evidence so no conversation is lost.
      if (response.type === "answer" || response.type === "no_results") {
        try {
          await addProjectItem(projectId, {
            item_type: "search_result",
            title: trimmed,
            metadata: {
              query: trimmed,
              answer_summary: response.assistant_message || response.message,
              result_payload: response,
            },
          });
          void loadProject();
        } catch {
          // Non-critical — evidence save failure shouldn't disrupt the search UX
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Search failed.";
      setChatError(msg);
      setTurns([...nextTurns, {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "The search could not complete. Please try again.",
        response: {
          type: "error", message: msg, assistant_message: msg,
          intent: "unknown", clarifying_questions: [], tool_calls: [],
          results: { closest_variables: [], relevant_reports: [], relevant_organizations: [], source_links: [], comparison: {} },
          limitations: [],
        },
      }]);
    } finally {
      setChatLoading(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void runProjectQuery(message);
  }

  function handleChipClick(option: string) {
    void runProjectQuery(lastQuery ? `${lastQuery}, ${option}` : option);
  }

  function handleItemSaved() {
    void loadProject();
  }

  function reopenSearchFromEvidence(item: ProjectItem) {
    const meta = item.metadata;
    const response = meta?.result_payload as ChatResponse | undefined;
    if (!response) return;
    const query = (meta?.query as string | undefined) || item.title || "";
    setTurns([
      { id: crypto.randomUUID(), role: "user", content: query },
      { id: crypto.randomUUID(), role: "assistant", content: response.assistant_message || response.message, response },
    ]);
    setLastQuery(query);
    setConversationId(response.conversation_id);
    setDrawerItem(null);
  }

  async function addNote(event: FormEvent) {
    event.preventDefault();
    if (!noteText.trim()) return;
    try {
      await addProjectItem(projectId, {
        item_type: "note",
        title: noteText.trim().slice(0, 80),
        note: noteText.trim(),
        metadata: {},
      });
      setNoteText("");
      void loadProject();
    } catch (err) {
      setChatError(err instanceof Error ? err.message : "Could not add note.");
    }
  }

  async function removeItem(itemId: string) {
    try {
      await removeProjectItem(itemId);
      setItems(prev => prev.filter(i => i.id !== itemId));
    } catch (err) {
      setChatError(err instanceof Error ? err.message : "Could not remove item.");
    }
  }

  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    try {
      const next = await updateProject(projectId, {
        title: editTitle,
        description: editDescription,
        research_question: editQuestion,
      });
      setProject(next);
      setEditing(false);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not save changes.");
    }
  }

  async function doExport() {
    try {
      const md = await exportProjectMarkdown(projectId);
      setMarkdown(md);
      setShowMarkdown(true);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not export project.");
    }
  }

  async function feedbackFn(type: string) {
    try { await submitFeedback(answerId, type); } catch { /* non-critical */ }
  }

  const suggestedQueries = project && !hasQueried ? generateSuggestedQueries(project) : [];

  if (!project && !loadError) {
    return <PlaceholderPage title="Loading project" description="Fetching your research workspace…" />;
  }

  return (
    <div className="project-workspace">
      {/* ── Header ── */}
      <div className="project-workspace-header">
        {loadError && <div className="notice error" role="alert" style={{ marginBottom: 8 }}>{loadError}</div>}
        <div className="pwh-inner">
          <div className="pwh-main">
            <h1 className="pwh-title">{project?.title || "Project"}</h1>
            {project?.research_question && (
              <p className="pwh-question">{project.research_question}</p>
            )}
            <div className="project-stat-row">
              {stats.searches > 0 && <span>{stats.searches} search{stats.searches !== 1 ? "es" : ""}</span>}
              {stats.variables > 0 && <span>{stats.variables} variable{stats.variables !== 1 ? "s" : ""}</span>}
              {stats.reports > 0 && <span>{stats.reports} report{stats.reports !== 1 ? "s" : ""}</span>}
              {stats.sources > 0 && <span>{stats.sources} source{stats.sources !== 1 ? "s" : ""}</span>}
              {stats.notes > 0 && <span>{stats.notes} note{stats.notes !== 1 ? "s" : ""}</span>}
              {items.length === 0 && <span className="project-stat-empty">No saved evidence yet</span>}
            </div>
          </div>
          <div className="pwh-actions">
            <button type="button" onClick={() => void doExport()}>Export brief</button>
            <button type="button" onClick={() => setEditing(!editing)}>
              {editing ? "Cancel" : "Edit"}
            </button>
          </div>
        </div>

        {/* Edit panel */}
        {editing && (
          <form className="project-edit-form" onSubmit={saveEdit}>
            <label>Title<input value={editTitle} onChange={e => setEditTitle(e.target.value)} required /></label>
            <label>Research question<input value={editQuestion} onChange={e => setEditQuestion(e.target.value)} /></label>
            <label>Description<textarea value={editDescription} onChange={e => setEditDescription(e.target.value)} rows={2} /></label>
            <button type="submit">Save</button>
          </form>
        )}

        {/* Markdown export */}
        {showMarkdown && markdown && (
          <div className="project-export-area">
            <div className="project-export-head">
              <span>Markdown brief</span>
              <button type="button" onClick={() => setShowMarkdown(false)}>Close</button>
            </div>
            <textarea className="markdown-export" value={markdown} readOnly rows={10} />
          </div>
        )}
      </div>

      {/* ── Body ── */}
      <div className="project-workspace-body">
        {/* Main column */}
        <main className="project-workspace-main">
          {/* Search input */}
          <div className="search-area">
            <form onSubmit={onSubmit}>
              <div className="search-row">
                <Search size={17} className="search-icon" aria-hidden="true" />
                <input
                  value={message}
                  onChange={e => setMessage(e.target.value)}
                  placeholder="Ask a data question for this project…"
                  autoFocus
                  aria-label="Project search query"
                />
                <button type="submit" disabled={chatLoading || !message.trim()}>
                  {chatLoading ? "Searching…" : "Search"}
                </button>
              </div>
            </form>

            {suggestedQueries.length > 0 && (
              <div className="example-chips">
                {suggestedQueries.map(q => (
                  <button key={q} type="button" className="chip" onClick={() => void runProjectQuery(q)}>
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>

          {chatError && <div className="notice error" role="alert">{chatError}</div>}

          {(latestResponse || chatLoading) && (
            <div className="result-area">
              {chatLoading && !latestResponse && <SearchingState />}
              {latestResponse && (
                <>
                  {chatLoading && <SearchingBanner />}
                  <AnswerSummary response={latestResponse} loading={chatLoading} />

                  {isClarification && clarifyingQuestions.length > 0 && (
                    <ClarificationPanel questions={clarifyingQuestions} onChoose={handleChipClick} />
                  )}
                  {hasResults && clarifyingQuestions.length > 0 && (
                    <NarrowChips questions={clarifyingQuestions} onChoose={handleChipClick} />
                  )}
                  {hasResults && latestResponse && (
                    <ResultSections
                      results={latestResponse.results}
                      limitations={latestResponse.limitations}
                      onViewEvidence={setDrawerItem}
                      projectId={projectId}
                      onItemSaved={handleItemSaved}
                    />
                  )}
                  {hasResults && !chatLoading && (
                    <div className="feedback-row">
                      <button type="button" onClick={() => void feedbackFn("thumbs_up")}>Useful</button>
                      <button type="button" onClick={() => void feedbackFn("thumbs_down")}>Not useful</button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </main>

        {/* Right sidebar */}
        <aside className="project-workspace-sidebar">
          {/* Quick note */}
          <div className="pws-section">
            <form onSubmit={addNote} className="quick-note-form">
              <textarea
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                placeholder="Add a research note…"
                rows={3}
              />
              <button type="submit" disabled={!noteText.trim()}>Add note</button>
            </form>
          </div>

          {/* Evidence basket */}
          <div className="pws-section pws-section-grow">
            <div className="pws-tabs">
              <button
                type="button"
                className={sidebarTab === "evidence" ? "active" : ""}
                onClick={() => setSidebarTab("evidence")}
              >
                Evidence
                {evidenceItems.length > 0 && <span className="pws-tab-count">{evidenceItems.length}</span>}
              </button>
              <button
                type="button"
                className={sidebarTab === "notes" ? "active" : ""}
                onClick={() => setSidebarTab("notes")}
              >
                Notes
                {noteItems.length > 0 && <span className="pws-tab-count">{noteItems.length}</span>}
              </button>
            </div>

            <div className="evidence-list">
              {sidebarTab === "evidence" && (
                <>
                  {evidenceItems.length === 0 && (
                    <p className="sidebar-note">Run a search — results are saved here automatically. You can also save individual variables, reports, and sources from each result.</p>
                  )}
                  {evidenceItems.map(item => {
                    const isSearch = item.item_type === "search_result";
                    const drawerData = isSearch ? null : projectItemToDrawerItem(item);
                    const isClickable = isSearch
                      ? Boolean(item.metadata?.result_payload)
                      : Boolean(drawerData);
                    const handleClick = isSearch
                      ? () => reopenSearchFromEvidence(item)
                      : drawerData ? () => setDrawerItem(drawerData) : undefined;
                    return (
                      <div key={item.id} className="evidence-item">
                        <button
                          type="button"
                          className={`evidence-item-content${isClickable ? " clickable" : ""}`}
                          onClick={handleClick}
                        >
                          <span className={`evidence-type-tag et-${item.item_type}`}>
                            {evidenceTypeLabel(item.item_type)}
                          </span>
                          <span className="evidence-item-title">{item.title || item.item_type}</span>
                        </button>
                        <button
                          type="button"
                          className="evidence-item-remove"
                          aria-label={`Remove ${item.title || item.item_type}`}
                          onClick={() => void removeItem(item.id)}
                        >
                          ×
                        </button>
                      </div>
                    );
                  })}
                </>
              )}

              {sidebarTab === "notes" && (
                <>
                  {noteItems.length === 0 && (
                    <p className="sidebar-note">Your notes will appear here.</p>
                  )}
                  {noteItems.map(item => (
                    <div key={item.id} className="note-item">
                      <p className="note-item-text">{item.note || item.title}</p>
                      <div className="note-item-foot">
                        <span className="note-item-date">{formatDate(item.created_at)}</span>
                        <button type="button" onClick={() => void removeItem(item.id)}>Remove</button>
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
        </aside>
      </div>

      <DetailDrawer item={drawerItem} onClose={() => setDrawerItem(null)} />
    </div>
  );
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
        <h1>Data Map</h1>
        <p>Explore geographies with available reports, variables, sources, and organizations.</p>
        {error && <div className="notice error" role="alert">{error}</div>}
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
    </main>
  );
}

function NotFoundPage({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <main className="main-content narrow-content">
      <PageHeader title="Page not found" description="The requested page does not exist." />
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
