import { useEffect, useState } from 'react';
import { api, ApiError } from '../api';
import type { Backend, Settings, SettingsUpdate, TempScale, UnitSystem } from '../types';

interface Props {
  onClose?: () => void; // modal mode when provided; omit for the inline nav section
}

// The operator surface (SDD Section 7): LLM backend, model, hyperparameters, and display defaults.
// Overrides apply to the running server and take effect on the next request; the config file stays
// the source of the default (Reset returns to it). No clinical threshold is a setting; API keys are
// environment secrets and are never entered here. Renders as a modal when `onClose` is given, or
// inline as a section (in the side nav) when it is not.
export function SettingsPanel({ onClose }: Props): JSX.Element {
  const [loaded, setLoaded] = useState<Settings | null>(null);
  const [form, setForm] = useState<Settings | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([api.getSettings(), api.models().catch(() => [])])
      .then(([s, m]) => { if (live) { setLoaded(s); setForm(s); setModels(m); } })
      .catch((e) => { if (live) setErr(e instanceof ApiError ? e.message : String(e)); });
    return () => { live = false; };
  }, []);

  const set = <K extends keyof Settings>(k: K, v: Settings[K]): void => {
    setSaved(false);
    setForm((f) => (f ? { ...f, [k]: v } : f));
  };

  // Only send fields the operator actually changed, so `overridden` stays meaningful.
  const diff = (): SettingsUpdate => {
    if (!loaded || !form) return {};
    const u: SettingsUpdate = {};
    if (form.backend !== loaded.backend) u.backend = form.backend as Backend;
    if (form.base_url !== loaded.base_url) u.base_url = form.base_url;
    if (form.generation_model !== loaded.generation_model) u.generation_model = form.generation_model;
    if (form.temperature !== loaded.temperature) u.temperature = form.temperature;
    if (form.context_window !== loaded.context_window) u.context_window = form.context_window;
    if (form.embedding_model !== loaded.embedding_model) u.embedding_model = form.embedding_model;
    if (form.unit_system !== loaded.unit_system) u.unit_system = form.unit_system as UnitSystem;
    if (form.temp_scale !== loaded.temp_scale) u.temp_scale = form.temp_scale as TempScale;
    return u;
  };

  const save = async (): Promise<void> => {
    setBusy(true); setErr(null);
    try {
      const next = await api.putSettings(diff());
      setLoaded(next); setForm(next); setSaved(true);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const reset = async (): Promise<void> => {
    setBusy(true); setErr(null);
    try {
      const next = await api.resetSettings();
      setLoaded(next); setForm(next); setSaved(true);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const isOverridden = (f: string): boolean => (loaded?.overridden ?? []).includes(f);
  const changed = Object.keys(diff()).length > 0;

  const content = (
    <>
        <div className="modal-head">
          <h2>Settings</h2>
          {onClose && (
            <button className="btn-ghost btn-sm" onClick={onClose} aria-label="Close">&times;</button>
          )}
        </div>
        <p className="card-hint">
          Runtime configuration for this server. Changes take effect on the next request; the config
          file remains the default (Reset returns to it). API keys are set as environment secrets, not here.
        </p>

        {err && <div className="notice err">{err}</div>}
        {!form ? (
          <p className="spinner">Loading settings…</p>
        ) : (
          <>
            <h3 className="set-group">Language model</h3>
            <div className="grid">
              <div className="field">
                <label>Backend {isOverridden('backend') && <span className="ov">override</span>}</label>
                <select value={form.backend} onChange={(e) => set('backend', e.target.value)}>
                  <option value="ollama">Ollama (local)</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                </select>
              </div>
              <div className="field">
                <label>Model {isOverridden('generation_model') && <span className="ov">override</span>}</label>
                {models.length > 0 ? (
                  <select value={form.generation_model} onChange={(e) => set('generation_model', e.target.value)}>
                    {!models.includes(form.generation_model) && <option value={form.generation_model}>{form.generation_model}</option>}
                    {models.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                ) : (
                  <input value={form.generation_model} onChange={(e) => set('generation_model', e.target.value)} />
                )}
              </div>
            </div>
            <div className="grid">
              <div className="field">
                <label>Temperature: <b>{form.temperature.toFixed(2)}</b> {isOverridden('temperature') && <span className="ov">override</span>}</label>
                <input type="range" min="0" max="1" step="0.05" value={form.temperature}
                  onChange={(e) => set('temperature', Number(e.target.value))} />
              </div>
              <div className="field">
                <label>Context window {isOverridden('context_window') && <span className="ov">override</span>}</label>
                <input type="number" min="512" step="512" value={form.context_window}
                  onChange={(e) => set('context_window', Number(e.target.value))} />
              </div>
            </div>
            <div className="field">
              <label>Base URL {isOverridden('base_url') && <span className="ov">override</span>}</label>
              <input value={form.base_url} onChange={(e) => set('base_url', e.target.value)} />
            </div>
            <div className="field">
              <label>Embedding model {isOverridden('embedding_model') && <span className="ov">override</span>}</label>
              <input value={form.embedding_model} onChange={(e) => set('embedding_model', e.target.value)} />
            </div>

            <h3 className="set-group">Display defaults</h3>
            <div className="grid">
              <div className="field">
                <label>Unit system {isOverridden('unit_system') && <span className="ov">override</span>}</label>
                <select value={form.unit_system} onChange={(e) => set('unit_system', e.target.value)}>
                  <option value="us">US</option>
                  <option value="metric">Metric</option>
                </select>
              </div>
              <div className="field">
                <label>Temperature scale {isOverridden('temp_scale') && <span className="ov">override</span>}</label>
                <select value={form.temp_scale} onChange={(e) => set('temp_scale', e.target.value)}>
                  <option value="F">Fahrenheit</option>
                  <option value="C">Celsius</option>
                </select>
              </div>
            </div>

            <div className="btn-row">
              <button className="btn-primary" onClick={() => void save()} disabled={busy || !changed}>
                {busy ? 'Saving…' : saved && !changed ? 'Saved' : 'Save changes'}
              </button>
              <button className="btn-ghost" onClick={() => void reset()} disabled={busy || (loaded?.overridden.length ?? 0) === 0}>
                Reset to config defaults
              </button>
            </div>
          </>
        )}
    </>
  );

  if (!onClose) {
    return <div className="card settings-inline">{content}</div>;
  }
  return (
    <div className="modal-scrim" role="dialog" aria-modal="true" aria-label="Settings" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        {content}
      </div>
    </div>
  );
}
