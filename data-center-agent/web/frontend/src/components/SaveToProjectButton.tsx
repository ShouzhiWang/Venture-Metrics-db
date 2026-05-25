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
};

export function SaveToProjectButton({ payload, label = "Save to project", onAuthRequired }: Props) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [newProjectTitle, setNewProjectTitle] = useState("");
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
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
  }, [open, onAuthRequired]);

  async function save() {
    setSaving(true);
    setStatus("");
    try {
      let projectId = selectedProjectId;
      if (!projectId) {
        const title = newProjectTitle.trim();
        if (!title) {
          setStatus("Choose a project or enter a new project title.");
          return;
        }
        const project = await createProject({ title });
        projectId = project.id;
        setProjects([project, ...projects]);
      }
      await addProjectItem(projectId, payload);
      setStatus("Saved.");
      setOpen(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not save to project.";
      if (message.toLowerCase().includes("login")) onAuthRequired?.();
      setStatus(message);
    } finally {
      setSaving(false);
    }
  }

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
            <button type="button" onClick={save} disabled={saving}>{saving ? "Saving..." : "Save"}</button>
            <button type="button" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
