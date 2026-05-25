import { FormEvent, useEffect, useState } from "react";
import type React from "react";
import { Search } from "lucide-react";
import { getCurrentUser, login, logout, register, sendChat, submitFeedback, type ChatHistoryItem, type User } from "./api";
import { AnswerSummary } from "./components/AnswerSummary";
import { ResultSections } from "./components/ResultSections";
import { DetailDrawer, type DrawerItem } from "./components/DetailDrawer";
import type { ChatResponse, ClarifyingQuestion } from "./types";

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

function DataDiscoveryPage() {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [drawerItem, setDrawerItem] = useState<DrawerItem | null>(null);
  const [lastQuery, setLastQuery] = useState("");
  const [answerId, setAnswerId] = useState(() => `answer-${Date.now()}`);

  const latestAssistant = [...turns].reverse().find(t => t.role === "assistant");
  const hasTurns = turns.length > 0;

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
      const response = await sendChat(trimmed, {}, historyFromTurns(nextTurns));
      const assistantTurn: Turn = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.assistant_message || response.message,
        response,
      };
      setTurns([...nextTurns, assistantTurn]);
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

  const latestResponse = latestAssistant?.response;
  const isClarification = latestResponse?.type === "clarification";
  const hasResults = latestResponse && latestResponse.type !== "clarification";
  const clarifyingQuestions = latestResponse?.clarifying_questions ?? [];

  return (
    <>
      <main className="main-content">
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
        <NavLink href="/history" path={path} onNavigate={onNavigate}>History</NavLink>
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
  if (path === "/data" || path === "/") return <DataDiscoveryPage />;
  if (path === "/login") return <AuthPage mode="login" user={user} onAuthed={nextUser => { setUser(nextUser); navigate("/data"); }} />;
  if (path === "/register") return <AuthPage mode="register" user={user} onAuthed={nextUser => { setUser(nextUser); navigate("/data"); }} />;
  if (path === "/history") return <ProtectedPage user={user} authLoading={authLoading} navigate={navigate}><HistoryPage /></ProtectedPage>;
  if (path === "/projects") return <ProtectedPage user={user} authLoading={authLoading} navigate={navigate}><ProjectsPage onNavigate={navigate} /></ProtectedPage>;
  if (path.startsWith("/projects/")) {
    return (
      <ProtectedPage user={user} authLoading={authLoading} navigate={navigate}>
        <ProjectDetailPage projectId={decodeURIComponent(path.replace("/projects/", ""))} />
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

function HistoryPage() {
  return (
    <PlaceholderPage
      title="History"
      description="Saved query history will appear here after authentication and server-side conversation storage are added."
    />
  );
}

function ProjectsPage({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <main className="main-content">
      <PageHeader
        title="Research Projects"
        description="Group searches, source notes, and selected variables into project workspaces."
      />
      <div className="list-panel">
        <button type="button" onClick={() => onNavigate("/projects/demo-project")}>
          Demo project
        </button>
        <p>Project storage is not connected yet. This route shows the intended workspace structure.</p>
      </div>
    </main>
  );
}

function ProjectDetailPage({ projectId }: { projectId: string }) {
  return (
    <main className="main-content narrow-content">
      <PageHeader
        title="Project"
        description={`Project workspace placeholder: ${projectId || "unknown project"}.`}
      />
      <section className="content-section">
        <h2>Saved items</h2>
        <p>Saved variables, reports, organizations, and notes will be listed here once project persistence is available.</p>
      </section>
    </main>
  );
}

function MapPage() {
  return (
    <PlaceholderPage
      title="Dynamic Map"
      description="A geography-first view of variables, sources, and ecosystem organizations will be added after the map data model is ready."
    />
  );
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
