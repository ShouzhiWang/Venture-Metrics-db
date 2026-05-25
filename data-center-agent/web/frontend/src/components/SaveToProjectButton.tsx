import { useEffect, useState } from "react";
import { addProjectItem, createProject, listProjects } from "../api";
import type { ProjectItem, ResearchProject } from "../types";

type SavePayload = {
  item_type: ProjectItem["item_type"];
  item_id?: string | null;
  title: string;
  metadata: Record<string, unknown>;
};

type Props = {
  payload: SavePayload;
  label?: string;
  onAuthRequired?: () => void;
  onSaved?: () => void;
  /** If provided, save directly to this project without showing a picker */
  projectId?: string;
};

export function SaveToProjectButton({ payload, label = "Save", onAuthRequired, onSaved, projectId }: Props) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [newProjectTitle, setNewProjectTitle] = useState("");
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || projectId) return;
    let active = true;
    listProjects()
      .then(items => {
        if (!active) return;
        setProjects(items);
        setSelectedProjectId(items[0]?.id || "");
      })
      .catch(err => {
        const message = err instanceof Error ? err.message : "Could not load projects.";
        if (message.toLowerCase().includes("login")) onAuthRequired?.();
        if (active) setStatus(message);
      });
    return () => {
      active = false;
    };
  }, [open, projectId, onAuthRequired]);

  async function saveToProject(targetProjectId?: string) {
    setSaving(true);
    setStatus("");
    try {
      let pid = targetProjectId || selectedProjectId;
      if (!pid) {
        const t = newProjectTitle.trim();
        if (!t) {
          setStatus("Choose a project or enter a project name.");
          setSaving(false);
          return;
        }
        const project = await createProject({ title: t });
        pid = project.id;
        setProjects(prev => [project, ...prev]);
      }
      await addProjectItem(pid, payload);
      onSaved?.();
      if (projectId) {
        setStatus("Saved");
        setTimeout(() => setStatus(""), 2000);
      } else {
        setStatus("Saved.");
        setOpen(false);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not save to project.";
      if (message.toLowerCase().includes("login")) onAuthRequired?.();
      setStatus(message === "Saved" ? "" : message);
    } finally {
      setSaving(false);
    }
  }

  // Direct save mode (projectId provided — no picker needed)
  if (projectId) {
    return (
      <button
        type="button"
        className={`card-action-btn${status === "Saved" ? " card-action-saved" : ""}`}
        onClick={() => void saveToProject(projectId)}
        disabled={saving}
      >
        {saving ? "Saving…" : status === "Saved" ? "Saved" : (label || "Save")}
      </button>
    );
  }

  // Popover mode (no projectId — show project picker)
  return (
    <div className="save-project">
      <button type="button" className="card-action-btn" onClick={() => setOpen(!open)}>
        {label}
      </button>
      {open && (
        <div className="save-project-panel">
          {projects.length > 0 && (
            <label>
              Project
              <select value={selectedProjectId} onChange={event => setSelectedProjectId(event.target.value)}>
                {projects.map(project => (
                  <option key={project.id} value={project.id}>{project.title}</option>
                ))}
              </select>
            </label>
          )}
          <label>
            New project
            <input
              value={newProjectTitle}
              onChange={event => {
                setNewProjectTitle(event.target.value);
                if (event.target.value.trim()) setSelectedProjectId("");
              }}
              placeholder="Project title"
            />
          </label>
          {status && <p>{status}</p>}
          <div className="save-project-actions">
            <button type="button" onClick={() => void saveToProject()} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
            <button type="button" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
