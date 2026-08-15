/**
 * Karthik admin dashboard — extracted from production teleautomation-app.jsx.
 */
import React from 'react'
import { Spinner } from '../Loader.jsx'
import { formatIstDateTime as fmtIstDt } from '../utils/istTime.js'
import { AiEconomyPresetSection } from './AiEconomyPresetSection.jsx'

const w = React
const s = { Fragment: React.Fragment }

const K1 = typeof window !== 'undefined' && window.location.port === '3000'
const ve = K1 ? '' : (typeof window !== 'undefined'
  ? `${window.location.protocol}//${window.location.host}`
  : '')

function ButtonSpinner({ loading, loadingLabel, children }) {
  if (loading) {
    return (
      <s.Fragment>
        <Spinner size={14} className="ui-spinner--on-dark" />
        <span>{loadingLabel || 'Loading…'}</span>
      </s.Fragment>
    )
  }
  return children
}


function ct(e) {
  const t = String(e).match(/^account(\d+)$/i);
  if (t) {
    return `Account ${t[1]}`;
  } else {
    return e;
  }
}


function KarthikAssessmentScorecard({
  scorecard: e,
  approved: t,
  manualApprovalAt: r,
  onClose: n,
  onRerun: a,
  onToggleOverride: i,
  running: l
}) {
  w.useEffect(() => {
    function f(h) {
      if (h.key === "Escape") {
        if (n != null) {
          n();
        }
      }
    }
    document.addEventListener("keydown", f);
    return () => document.removeEventListener("keydown", f);
  }, [n]);
  if (!e) {
    return null;
  }
  const c = e.verdict;
  const o = e.ran_at ? fmtIstDt(e.ran_at) : "—";
  const u = c === "approved" ? "approved" : c === "needs_review" ? "review" : "failed";
  const d = c === "approved" ? "✓ Approved — Karthik is cleared" : c === "needs_review" ? "⚠ Needs review — borderline knowledge" : "✗ Failed — Karthik is blocked from drafting";
  return <div className="cand-modal-backdrop" onClick={f => f.target === f.currentTarget && (n == null ? undefined : n())} role="presentation"><div className="cand-modal cand-modal--xl assess-modal" role="dialog" aria-modal="true"><header className="cand-modal-header"><div><h3 className="cand-modal-title">Karthik assessment scorecard</h3><p className="cand-modal-sub">{e.assistant_name || "Karthik"} · model {e.model || "—"} · ran {o} · took {e.elapsed_sec ?? "?"}s</p></div><button type="button" className="cand-modal-close" onClick={n} aria-label="Close">×</button></header><div className={`assess-verdict assess-verdict--${u}`}><div className="assess-verdict-score"><span className="assess-verdict-num">{e.overall_score}%</span><span className="assess-verdict-label">overall</span></div><div className="assess-verdict-text"><div className="assess-verdict-title">{d}</div><div className="assess-verdict-summary">{e.summary}</div><div className="assess-verdict-tally"><span className="assess-tally-pill assess-tally-pill--passed">{e.passed} passed</span><span className="assess-tally-pill assess-tally-pill--review">{e.needs_review} need review</span><span className="assess-tally-pill assess-tally-pill--failed">{e.failed} failed</span></div></div></div>{!t && <div className="assess-gate-banner"><strong>AI suggestions are currently blocked.</strong> Either re-run the assessment after improving the business prompt, or manually override below.</div>}{t && r && <div className="assess-gate-banner assess-gate-banner--override"><strong>Manual override active.</strong> Karthik is cleared to draft despite the assessment result. Revoke any time using the toggle below.</div>}<div className="assess-results">{(e.results || []).map((f, h) => {
          const x = f.verdict === "passed" ? "passed" : f.verdict === "needs_review" ? "review" : "failed";
          return <details className={`assess-result assess-result--${x}`} open={true} key={f.id}><summary className="assess-result-head"><span className="assess-result-rank">{h + 1}</span><span className="assess-result-area">{f.area}</span><span className={`assess-result-score assess-result-score--${x}`}>{f.score_pct}%</span></summary><div className="assess-result-body">{f.notes && <div className="assess-result-notes">{f.notes}</div>}{f.forbidden_hit && f.forbidden_hit.length > 0 && <div className="assess-result-forbidden"><strong>⚠ Used forbidden phrasing:</strong> {f.forbidden_hit.join(", ")}</div>}<div className="assess-result-answer-head">Karthik answered:</div><pre className="assess-result-answer">{f.answer || "(no answer)"}</pre><div className="assess-result-grid"><div className="assess-result-col"><div className="assess-result-col-title">✓ Covered topics ({(f.covered || []).length})</div>{(f.covered || []).length === 0 ? <div className="assess-result-col-empty">none</div> : <ul className="assess-result-list assess-result-list--good">{f.covered.map(v => <li key={v}>{v}</li>)}</ul>}</div><div className="assess-result-col"><div className="assess-result-col-title">✗ Missing topics ({(f.missing || []).length})</div>{(f.missing || []).length === 0 ? <div className="assess-result-col-empty">none</div> : <ul className="assess-result-list assess-result-list--bad">{f.missing.map(v => <li key={v}>{v}</li>)}</ul>}</div></div></div></details>;
        })}</div><footer className="assess-footer">{e.verdict !== "approved" && <label className="assess-footer-override"><input type="checkbox" checked={!!r} onChange={f => i == null ? undefined : i(f.target.checked)} /><span>Override and approve Karthik manually</span></label>}<div className="assess-footer-spacer" /><button type="button" className="btn btn--ghost btn--sm" onClick={n}>Close</button><button type="button" className="btn btn--primary btn--sm" onClick={a} disabled={l} title="Re-run the assessment (typically after editing the business prompt)"><ButtonSpinner loading={l} loadingLabel="Assessing…">Re-run assessment</ButtonSpinner></button></footer></div></div>;
}


function AiSmartReplySettingsModal({
  open: e,
  onClose: t,
  onChange: r
}) {
  var re;
  var ue;
  var pe;
  var me;
  var fe;
  const [n, a] = w.useState(null);
  const [i, l] = w.useState(null);
  const [c, o] = w.useState(false);
  const [u, d] = w.useState(false);
  const [f, h] = w.useState("");
  const [x, v] = w.useState(null);
  const [g, p] = w.useState(false);
  const [m, _] = w.useState(false);
  const [y, k] = w.useState(null);
  const [T, S] = w.useState(false);
  const [E, b] = w.useState("");
  const [A, O] = w.useState("");
  const [L, M] = w.useState(false);
  const [C, Y] = w.useState(0);
  const J = q => {
    var I;
    if (q.config) {
      a(q.config);
    }
    if (q.health) {
      l(q.health);
    }
    if (typeof q.knowledge_entry_count == "number") {
      Y(q.knowledge_entry_count);
    } else if ((I = q.config) != null && I.knowledge_entries) {
      Y(q.config.knowledge_entries.length);
    }
  };
  const G = async () => {
    try {
      const I = await (await fetch(`${ve}/ai/smart-reply/assessment`)).json();
      if (I.status === "ok") {
        v(I);
      }
    } catch {}
  };
  w.useEffect(() => {
    if (!e) {
      return;
    }
    let q = false;
    async function I() {
      o(true);
      h("");
      try {
        const [Oe, Re, Pe] = await Promise.all([fetch(`${ve}/ai/smart-reply/config`), fetch(`${ve}/ai/smart-reply/assessment`), fetch(`${ve}/ai/smart-reply/evals`)]);
        const De = await Oe.json();
        const ye = await Re.json();
        const Le = await Pe.json();
        if (q) {
          return;
        }
        if (De.status === "ok") {
          J(De);
        } else {
          h(De.message || "Failed to load AI config");
        }
        if (ye.status === "ok") {
          v(ye);
        }
        if (Le.status === "ok" && Le.last_reply_evals) {
          k(Le.last_reply_evals);
        }
      } catch (Oe) {
        if (!q) {
          h(String(Oe.message || Oe));
        }
      } finally {
        if (!q) {
          o(false);
        }
      }
    }
    I();
    return () => {
      q = true;
    };
  }, [e]);
  const ce = async () => {
    if (!g) {
      p(true);
      h("");
      try {
        const I = await (await fetch(`${ve}/ai/smart-reply/assess`, {
          method: "POST"
        })).json();
        if (I.status === "ok") {
          await G();
          _(true);
        } else {
          h(I.message || "Assessment failed");
        }
      } catch (q) {
        h(String(q.message || q));
      } finally {
        p(false);
      }
    }
  };
  const ee = async () => {
    if (!T) {
      S(true);
      h("");
      try {
        const I = await (await fetch(`${ve}/ai/smart-reply/evals/replies`, {
          method: "POST"
        })).json();
        if (I.status === "ok") {
          k(I);
        } else {
          h(I.message || "Reply evals failed");
        }
      } catch (q) {
        h(String(q.message || q));
      } finally {
        S(false);
      }
    }
  };
  const B = async q => {
    try {
      if ((await (await fetch(`${ve}/ai/smart-reply/manual-approval`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          approved: !!q
        })
      })).json()).status === "ok") {
        G();
      }
    } catch {}
  };
  if (!e) {
    return null;
  }
  const Z = q => a(I => ({
    ...(I || {}),
    ...q
  }));
  const P = async () => {
    if (n) {
      d(true);
      h("");
      try {
        const {
          knowledge_entries: q,
          ...I
        } = n;
        const Re = await (await fetch(`${ve}/ai/smart-reply/config`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(I)
        })).json();
        if (Re.status === "ok") {
          J(Re);
          if (r != null) {
            r(Re.config, Re.health);
          }
          if (t != null) {
            t();
          }
        } else {
          h(Re.message || "Save failed");
        }
      } catch (q) {
        h(String(q.message || q));
      } finally {
        d(false);
      }
    }
  };
  const j = async () => {
    const q = E.trim();
    if (!!q && !L) {
      M(true);
      h("");
      try {
        const Oe = await (await fetch(`${ve}/ai/smart-reply/knowledge`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            content: q,
            title: A.trim() || undefined
          })
        })).json();
        if (Oe.status === "ok") {
          J(Oe);
          b("");
          O("");
          if (r != null) {
            r(Oe.config, Oe.health);
          }
        } else {
          h(Oe.message || "Failed to add knowledge");
        }
      } catch (I) {
        h(String(I.message || I));
      } finally {
        M(false);
      }
    }
  };
  const U = async q => {
    if (q) {
      h("");
      try {
        const Oe = await (await fetch(`${ve}/ai/smart-reply/knowledge/${encodeURIComponent(q)}`, {
          method: "DELETE"
        })).json();
        if (Oe.status === "ok") {
          J(Oe);
          if (r != null) {
            r(Oe.config, Oe.health);
          }
        } else {
          h(Oe.message || "Failed to remove entry");
        }
      } catch (I) {
        h(String(I.message || I));
      }
    }
  };
  const W = Array.isArray(n == null ? undefined : n.knowledge_entries) ? n.knowledge_entries : [];
  const H = i && !i.api_key_present;
  const Ne = q => {
    if (q.config) {
      J(q);
    }
    if (q.health && r != null) {
      r(q.config, q.health);
    }
  };
  return <div className="ai-settings-overlay" role="dialog" aria-label="AI smart reply settings"><div className="ai-settings-card"><header className="ai-settings-header"><div><div className="ai-settings-title">AI Smart Reply</div><div className="ai-settings-sub">Auto-respond to inbound DMs and qualify leads toward WhatsApp.</div></div><button type="button" className="ai-settings-close" onClick={t} aria-label="Close">×</button></header>{c && !n && <div className="empty-state">Loading…</div>}{n && <div className="ai-settings-body">{H && <div className="ai-settings-warning" role="alert"><strong>API key missing.</strong> Set the <code>AI_API_KEY</code> (or <code>OPENAI_API_KEY</code>) environment variable on the backend, then restart the service.</div>}<AiEconomyPresetSection apiBase={ve} config={n} onConfigPatched={Ne} setError={h} /><label className="ai-settings-row ai-settings-row--toggle"><span><strong>Enable Karthik (suggestion mode)</strong><span className="ai-settings-row-hint">When on, the inbox shows a "Suggest reply" button that drafts a message for you to review. <strong>Nothing is ever sent automatically</strong> — every outbound goes out only when you click Send.</span></span><input type="checkbox" checked={!!n.enabled} onChange={q => Z({
            enabled: q.target.checked
          })} /></label><label className="ai-settings-row ai-settings-row--toggle"><span><strong>Karthik group post rewrite</strong><span className="ai-settings-row-hint">Each posting cycle, Karthik rephrases your saved group broadcast (same offer, different wording). Phone / WhatsApp lines stay fixed.{i != null && i.group_rewrite_ready ? <em> Ready — active on next cycle.</em> : (i == null ? undefined : i.group_rewrite_enabled) === false ? <em> Off.</em> : i != null && i.api_key_present ? <em> Falls back to emoji shuffle if unavailable.</em> : <em> Needs AI_API_KEY on the server.</em>}</span></span><input type="checkbox" checked={n.group_rewrite_enabled !== false} onChange={q => Z({
            group_rewrite_enabled: q.target.checked
          })} /></label><div className={`ai-assessment-card ai-assessment-card--${x != null && x.approved ? "approved" : x != null && x.last_assessment ? "review" : "pending"}`}><div className="ai-assessment-card-head"><div className="ai-assessment-card-title">Karthik knowledge gate{x != null && x.approved ? <span className="ai-assessment-pill ai-assessment-pill--approved">✓ Approved</span> : x != null && x.last_assessment ? <span className="ai-assessment-pill ai-assessment-pill--blocked">✗ Blocked</span> : <span className="ai-assessment-pill ai-assessment-pill--pending">Never assessed</span>}</div><div className="ai-assessment-card-actions">{(x == null ? undefined : x.last_assessment) && <button type="button" className="btn btn--ghost btn--sm" onClick={() => _(true)}>View scorecard</button>}<button type="button" className="btn btn--primary btn--sm" onClick={ce} disabled={g} title="Run the knowledge battery — 8 LLM questions covering project, services, audience, conversation style, conversion flow, and restrictions."><ButtonSpinner loading={g} loadingLabel="Assessing…">{x != null && x.last_assessment ? "Re-assess" : "Assess Karthik"}</ButtonSpinner></button></div></div><p className="ai-assessment-card-hint">Karthik must score ≥75% on the knowledge battery before he's allowed to draft suggestions for real clients. The battery tests project understanding, services & pricing, target audience, conversation handling (incl. Telugu), conversion flow, and safety rules.</p>{(x == null ? undefined : x.last_assessment) && <div className="ai-assessment-summary"><span className="ai-assessment-score">{x.last_assessment.overall_score}%<em>overall</em></span><span className="ai-assessment-breakdown"><strong>{x.last_assessment.passed}</strong> passed · <strong>{x.last_assessment.needs_review}</strong> need review · <strong>{x.last_assessment.failed}</strong> failed</span><span className="ai-assessment-when">last run {fmtIstDt(x.last_assessment.ran_at)}</span></div>}{(x == null ? undefined : x.last_assessment) && !x.approved && <label className="ai-assessment-override"><input type="checkbox" checked={!!x.manual_approval_at} onChange={q => B(q.target.checked)} /><span><strong>Operator override:</strong> approve Karthik manually despite the failed assessment. <em>Only use when you've re-read the answers yourself and accept the risk.</em></span></label>}</div><div className={`ai-assessment-card ai-assessment-card--${(y == null ? undefined : y.verdict) === "passed" ? "approved" : y ? "review" : "pending"}`}><div className="ai-assessment-card-head"><div className="ai-assessment-card-title">Playbook reply evals{(y == null ? undefined : y.verdict) === "passed" ? <span className="ai-assessment-pill ai-assessment-pill--approved">✓ {y.passed}/{y.total}</span> : y ? <span className="ai-assessment-pill ai-assessment-pill--blocked">✗ {y.failed} failed</span> : <span className="ai-assessment-pill ai-assessment-pill--pending">Not run</span>}</div><button type="button" className="btn btn--ghost btn--sm" onClick={ee} disabled={T} title="Fast deterministic tests — no LLM. Edit config/karthik/ then run."><ButtonSpinner loading={T} loadingLabel="Running…">Run reply evals</ButtonSpinner></button></div><p className="ai-assessment-card-hint">Rules live in <code>config/karthik/</code> (playbooks + markers + evals). Reply evals check post-processing — handoffs, pricing, slot order, proxy, language.{(i == null ? undefined : i.playbooks) && <s.Fragment> Playbook v{i.playbooks.version}, {i.playbooks.marker_groups} marker groups.</s.Fragment>}</p>{((re = y == null ? undefined : y.results) == null ? undefined : re.some(q => !q.passed)) && <ul className="ai-eval-failures">{y.results.filter(q => !q.passed).map(q => <li key={q.id}><strong>{q.id}</strong>: {(q.failures || [q.error]).join("; ")}</li>)}</ul>}</div><label className="ai-settings-row"><span>Assistant name</span><input type="text" value={n.assistant_name || ""} onChange={q => Z({
            assistant_name: q.target.value
          })} placeholder="Karthik" maxLength={32} /></label><label className="ai-settings-row"><span>Model</span><input type="text" value={n.model || ""} onChange={q => Z({
            model: q.target.value
          })} placeholder="gpt-4o-mini" /></label><label className="ai-settings-row"><span>WhatsApp link (CTA)</span><input type="text" value={n.whatsapp_link || ""} onChange={q => Z({
            whatsapp_link: q.target.value
          })} placeholder="https://wa.me/..." /></label><section className="ai-work-hours-section"><label className="ai-settings-row ai-settings-row--toggle"><span><strong>Working hours only</strong><span className="ai-settings-row-hint">Karthik auto-replies only inside these hours. Outside hours he sends one short offline line, then stays quiet until the next window.{((ue = i == null ? undefined : i.work_hours) == null ? undefined : ue.within_hours) === false && ((pe = i == null ? undefined : i.work_hours) == null ? undefined : pe.enabled) && <em> Currently offline.</em>}{((me = i == null ? undefined : i.work_hours) == null ? undefined : me.within_hours) === true && ((fe = i == null ? undefined : i.work_hours) == null ? undefined : fe.enabled) && <em> Currently in hours.</em>}</span></span><input type="checkbox" checked={!!n.work_hours_enabled} onChange={q => Z({
              work_hours_enabled: q.target.checked
            })} /></label>{n.work_hours_enabled && <s.Fragment><div className="ai-settings-grid"><label className="ai-settings-row"><span>Start (24h)</span><input type="time" value={n.work_hours_start || "09:00"} onChange={q => Z({
                  work_hours_start: q.target.value.slice(0, 5)
                })} /></label><label className="ai-settings-row"><span>End (24h)</span><input type="time" value={n.work_hours_end || "21:00"} onChange={q => Z({
                  work_hours_end: q.target.value.slice(0, 5)
                })} /></label></div><label className="ai-settings-row ai-settings-row--full"><span>Offline message (sent once outside hours)</span><textarea rows={2} value={n.work_hours_offline_message || ""} onChange={q => Z({
                work_hours_offline_message: q.target.value
              })} placeholder="I'm currently offline. I'll reply in working hours." /></label><p className="ai-knowledge-hint">Timezone: {n.work_hours_timezone || "Asia/Kolkata"} (IST)</p></s.Fragment>}</section><section className="ai-knowledge-section"><div className="ai-knowledge-head"><span className="ai-knowledge-title">Teach Karthik (add-on knowledge)</span><span className="ai-knowledge-count">{C} saved</span></div><p className="ai-knowledge-hint">New prompts are <strong>added</strong> to Karthik's memory — they never replace the master prompt or earlier lessons.</p><label className="ai-settings-row"><span>Label (optional)</span><input type="text" value={A} onChange={q => O(q.target.value)} placeholder="e.g. May pricing update" maxLength={80} /></label><label className="ai-settings-row ai-settings-row--full"><span>New prompt / knowledge to learn</span><textarea rows={5} value={E} onChange={q => b(q.target.value)} placeholder="Paste new instructions, pricing, scripts, or rules…" /></label><div className="ai-knowledge-actions"><button type="button" className="btn btn--accent btn--sm" onClick={j} disabled={L || !E.trim()}><ButtonSpinner loading={L} loadingLabel="Adding…">Add to Karthik's knowledge</ButtonSpinner></button></div>{W.length > 0 && <ul className="ai-knowledge-list">{W.map((q, I) => {
              const Oe = (q.content || "").slice(0, 120);
              const Re = q.added_at ? fmtIstDt(q.added_at) : "";
              return <li className="ai-knowledge-item" key={q.id || I}><div className="ai-knowledge-item-head"><strong>#{I + 1}{q.title ? ` · ${q.title}` : ""}</strong>{Re && <span className="ai-knowledge-item-when">{Re}</span>}<button type="button" className="btn btn--ghost btn--xs ai-knowledge-remove" onClick={() => U(q.id)} title="Remove this entry only">Remove</button></div><p className="ai-knowledge-item-preview">{Oe}{(q.content || "").length > 120 ? "…" : ""}</p></li>;
            })}</ul>}</section><details className="ai-knowledge-base ai-master-prompt"><summary>Master prompt</summary><p className="ai-knowledge-hint">Core foundation — services, pricing, tone, and rules. Editing this replaces the master prompt only. All "Teach Karthik" entries above are kept.</p><label className="ai-settings-row ai-settings-row--full"><span>Master prompt (foundation)</span><textarea rows={6} value={n.business_prompt || ""} onChange={q => Z({
              business_prompt: q.target.value
            })} placeholder="Core Karthik system prompt…" /></label></details><div className="ai-settings-grid"><label className="ai-settings-row"><span>Min reply delay (sec)</span><input type="number" min={0} max={300} value={n.min_delay_seconds ?? 4} onChange={q => Z({
              min_delay_seconds: Number(q.target.value)
            })} /></label><label className="ai-settings-row"><span>Max reply delay (sec)</span><input type="number" min={0} max={300} value={n.max_delay_seconds ?? 14} onChange={q => Z({
              max_delay_seconds: Number(q.target.value)
            })} /></label><label className="ai-settings-row"><span>Pause if human replied within (min)</span><input type="number" min={0} max={1440} value={n.human_pause_minutes ?? 10} onChange={q => Z({
              human_pause_minutes: Number(q.target.value)
            })} /></label><label className="ai-settings-row"><span>Max AI replies per lead per day</span><input type="number" min={1} max={100} value={n.max_replies_per_lead_per_day ?? 12} onChange={q => Z({
              max_replies_per_lead_per_day: Number(q.target.value)
            })} /></label><label className="ai-settings-row"><span>Max AI replies per account per hour</span><input type="number" min={1} max={500} value={n.max_replies_per_account_per_hour ?? 30} onChange={q => Z({
              max_replies_per_account_per_hour: Number(q.target.value)
            })} /></label><label className="ai-settings-row"><span>Min confidence (0–1)</span><input type="number" step={0.05} min={0} max={1} value={n.min_confidence ?? 0.45} onChange={q => Z({
              min_confidence: Number(q.target.value)
            })} /></label></div>{f && <div className="ai-settings-error" role="alert">{f}</div>}<footer className="ai-settings-footer"><button type="button" className="btn btn--ghost btn--sm" onClick={t} disabled={u}>Close</button><button type="button" className="btn btn--primary btn--sm" onClick={P} disabled={u}><ButtonSpinner loading={u} loadingLabel="Saving…">Save settings</ButtonSpinner></button></footer></div>}</div>{m && (x == null ? undefined : x.last_assessment) && <KarthikAssessmentScorecard scorecard={x.last_assessment} approved={x.approved} manualApprovalAt={x.manual_approval_at} onClose={() => _(false)} onRerun={ce} onToggleOverride={B} running={g} />}</div>;
}


function Cr({
  label: e,
  value: t,
  sub: r,
  tone: n
}) {
  return <div className={`admin-metric admin-metric--${n || "default"}`}><span className="admin-metric-label">{e}</span><strong className="admin-metric-value">{t}</strong>{r && <span className="admin-metric-sub">{r}</span>}</div>;
}
function Fx({
  temp: e
}) {
  const t = e === "hot" ? "hot" : e === "warm" ? "warm" : "cold";
  return <span className={`admin-temp admin-temp--${t}`}>{e}</span>;
}
function _Component34({
  status: e
}) {
  return <span className={`admin-status admin-status--${e}`}>{e}</span>;
}
function _Component33({
  steps: e
}) {
  if (e == null || !e.length) {
    return null;
  }
  const t = Math.max(...e.map(r => r.count || 0), 1);
  return <div className="admin-funnel">{e.map(r => <div className="admin-funnel-row" key={r.step}><span className="admin-funnel-label">{r.step}</span><div className="admin-funnel-track"><div className="admin-funnel-fill" style={{
          width: `${Math.max(4, r.count / t * 100)}%`
        }} /></div><span className="admin-funnel-count">{r.count}</span><span className="admin-funnel-pct">{r.pct}%</span></div>)}</div>;
}


export function AdminPanel() {
  var m;
  var _;
  var y;
  var k;
  var T;
  var S;
  var E;
  const [e, t] = w.useState(null);
  const [r, n] = w.useState(true);
  const [a, i] = w.useState("");
  const [l, c] = w.useState(false);
  const [o, u] = w.useState("overview");
  const d = w.useCallback(async () => {
    try {
      const b = await fetch(`${ve}/admin/dashboard?window_hours=24`, { credentials: 'include' })
      const ct = b.headers.get('content-type') || ''
      if (!ct.includes('application/json')) {
        throw new Error(b.ok ? 'Admin API returned non-JSON — hard refresh and try again' : `Admin dashboard unavailable (${b.status})`)
      }
      const A = await b.json()
      if (!b.ok || A.status === 'error') {
        throw new Error(A.message || A.detail || `HTTP ${b.status}`)
      }
      t(A)
      i('')
    } catch (b) {
      i(String(b.message || b))
    } finally {
      n(false)
    }
  }, [])
  w.useEffect(() => {
    d();
    const b = window.setInterval(d, 15000);
    return () => clearInterval(b);
  }, [d]);
  const f = (e == null ? undefined : e.conversion) || {};
  const h = (e == null ? undefined : e.live_chat_summary) || {};
  const x = (e == null ? undefined : e.lead_summary) || {};
  const v = ((m = e == null ? undefined : e.karthik) == null ? undefined : m.stats) || {};
  const g = (e == null ? undefined : e.ai_config) || {};
  const p = [{
    id: "overview",
    label: "Overview"
  }, {
    id: "chats",
    label: "Live chats"
  }, {
    id: "leads",
    label: "Lead scoring"
  }, {
    id: "karthik",
    label: "Karthik"
  }, {
    id: "bugs",
    label: "Issues"
  }];
  return <div className="admin-dashboard"><header className="admin-header"><div><h1 className="admin-title">Admin · Karthik</h1><p className="admin-sub">Real-time monitoring · {e != null && e.generated_at ? fmtIstDt(e.generated_at) : "…"}</p></div><div className="admin-header-actions"><button type="button" className="btn btn--ghost btn--sm" onClick={d} disabled={r}>Refresh</button><button type="button" className="btn btn--accent btn--sm" onClick={() => c(true)}>AI controls</button></div></header><nav className="admin-tabs" role="tablist">{p.map(b => <button type="button" role="tab" aria-selected={o === b.id} className={`admin-tab${o === b.id ? " admin-tab--active" : ""}`} onClick={() => u(b.id)} key={b.id}>{b.label}</button>)}</nav>{r && !e && <p className="admin-loading">Loading dashboard…</p>}{a && <p className="admin-error" role="alert">{a}</p>}{e && o === "overview" && <div className="admin-grid"><section className="admin-card admin-card--wide"><h2>Conversion</h2><div className="admin-metrics"><Cr label="Total users" value={f.total_users ?? 0} /><Cr label="Active" value={f.active_users ?? 0} tone="blue" /><Cr label="Converted" value={f.converted_users ?? 0} tone="green" /><Cr label="Conversion %" value={`${f.conversion_rate_pct ?? 0}%`} tone="gold" /><Cr label="Avg response" value={f.avg_response_minutes != null ? `${f.avg_response_minutes}m` : "—"} /><Cr label="Avg msgs/user" value={f.avg_messages_per_user ?? 0} /></div><_Component33 steps={e.funnel} /></section><section className="admin-card"><h2>Live chats</h2><div className="admin-metrics admin-metrics--compact"><Cr label="Active" value={h.active ?? 0} tone="green" /><Cr label="Waiting" value={h.waiting ?? 0} tone="warn" /><Cr label="Flagged" value={h.flagged ?? 0} tone="danger" /></div></section><section className="admin-card"><h2>Lead temperature</h2><div className="admin-metrics admin-metrics--compact"><Cr label="Hot" value={x.hot ?? 0} tone="hot" /><Cr label="Warm" value={x.warm ?? 0} tone="warm" /><Cr label="Cold" value={x.cold ?? 0} tone="cold" /></div></section><section className="admin-card"><h2>Karthik (24h)</h2><div className="admin-metrics admin-metrics--compact"><Cr label="AI sends" value={v.sends ?? 0} /><Cr label="Skipped" value={v.skipped ?? 0} /><Cr label="Dup blocked" value={v.duplicates_prevented ?? 0} tone="green" /><Cr label="Long replies" value={v.long_replies ?? 0} tone={v.long_replies > 0 ? "warn" : "default"} /></div><p className="admin-hint">AI {g.enabled ? "ON" : "OFF"} · {g.mode} · delays {g.min_delay_seconds}–{g.max_delay_seconds}s</p></section><section className="admin-card admin-card--wide"><h2>Drop-off points</h2><ul className="admin-list">{Object.entries(((_ = e.behavior) == null ? undefined : _.drop_off_points) || {}).map(([b, A]) => <li key={b}><strong>{b.replace(/_/g, " ")}</strong> — {A}</li>)}</ul></section><section className="admin-card admin-card--wide"><h2>Common questions</h2><ul className="admin-list admin-list--questions">{(((y = e.behavior) == null ? undefined : y.common_questions) || []).map(b => <li key={b.text}><span>{b.text}</span> <em>({b.count})</em></li>)}</ul></section></div>}{e && o === "chats" && <section className="admin-card admin-card--full"><h2>Live chat monitor</h2><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>User</th><th>Status</th><th>Stage</th><th>Temp</th><th>Flags</th><th>Last message</th><th>Account</th></tr></thead><tbody>{(e.live_chats || []).map(b => {
              var A;
              var O;
              return <tr className={(A = b.flags) != null && A.length ? "admin-table-row--flagged" : ""} key={`${b.slot}:${b.user_id}`}><td><strong>{b.name}</strong>{b.username && <span className="admin-muted"> @{b.username.replace(/^@/, "")}</span>}</td><td><_Component34 status={b.status} /></td><td>{b.stage}</td><td><Fx temp={b.temperature} /></td><td>{((O = b.flags) == null ? undefined : O.join(", ")) || "—"}</td><td className="admin-cell-truncate" title={b.last_message}>{b.last_message || "—"}</td><td>{ct(b.slot)}</td></tr>;
            })}</tbody></table></div></section>}{e && o === "leads" && <section className="admin-card admin-card--full"><h2>Lead scoring</h2><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>User</th><th>Temp</th><th>Tech</th><th>Experience</th><th>Stage</th><th>CRM</th></tr></thead><tbody>{(e.lead_scoring || []).map(b => <tr key={`${b.slot}:${b.user_id}`}><td>{b.name}</td><td><Fx temp={b.temperature} /></td><td>{b.tech}</td><td>{b.experience}</td><td>{b.stage}</td><td>{b.crm_status}</td></tr>)}</tbody></table></div></section>}{e && o === "karthik" && <div className="admin-grid"><section className="admin-card"><h2>Performance (24h)</h2><ul className="admin-kv"><li><span>Sends</span><strong>{v.sends ?? 0}</strong></li><li><span>Success rate</span><strong>{((k = e.karthik) == null ? undefined : k.success_rate_pct) ?? 0}%</strong></li><li><span>Skipped</span><strong>{v.skipped ?? 0}</strong></li><li><span>Low confidence</span><strong>{v.low_confidence_sends ?? 0}</strong></li><li><span>Long replies</span><strong>{v.long_replies ?? 0}</strong></li><li><span>Queue cancelled</span><strong>{v.queue_cancelled ?? 0}</strong></li></ul></section><section className="admin-card"><h2>Quality control</h2><ul className="admin-kv"><li><span>One-reply guard</span><strong>{(T = e.quality) != null && T.one_reply_guard ? "Active" : "Off"}</strong></li><li><span>Dup blocked</span><strong>{((S = e.quality) == null ? undefined : S.duplicate_prevented_24h) ?? 0}</strong></li><li><span>Knowledge entries</span><strong>{g.knowledge_entries ?? 0}</strong></li><li><span>Work hours</span><strong>{g.work_hours_enabled ? `${g.work_hours_start}–${g.work_hours_end}` : "Off"}</strong></li></ul></section><section className="admin-card admin-card--wide"><h2>Recent AI events</h2><ul className="admin-event-list">{(((E = e.karthik) == null ? undefined : E.recent_events) || []).map((b, A) => <li key={`${b.t}-${A}`}><span className="admin-event-type">{b.type}</span>{b.slot && <span>{b.slot}</span>}{b.reason && <span className="admin-muted">{b.reason}</span>}<time>{b.t ? new Date(b.t).toLocaleTimeString("en-IN", {
                timeZone: "Asia/Kolkata"
              }) : ""}</time></li>)}</ul></section></div>}{e && o === "bugs" && <section className="admin-card admin-card--full"><h2>Bug & error monitor</h2><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Issue</th><th>Location</th><th>Impact</th><th>Status</th></tr></thead><tbody>{(e.bugs || []).map((b, A) => {
              var O;
              return <tr key={`${b.issue_type}-${A}`}><td>{(O = b.issue_type) == null ? undefined : O.replace(/_/g, " ")}</td><td><code>{b.location}</code></td><td>{b.user_impact || b.root_cause}</td><td><span className={`admin-bug-status admin-bug-status--${b.status || "open"}`}>{b.status || "open"}</span></td></tr>;
            })}</tbody></table></div></section>}<AiSmartReplySettingsModal open={l} onClose={() => {
      c(false);
      d();
    }} onChange={() => d()} /></div>;
}
