# Session handoff — demo video task (2026-07-21) — DONE

## Deliverable
`UniServe_Demo_Video.mp4` at the repo root. 3:03, 1600x900 h264 + aac audio
(Microsoft Ravi TTS narration), verified by extracting frames at ~12
timestamps and checking each against the expected scene. Script/storyboard:
`marketing/deck-assets/demo_video_script.md` (delivered regardless, per the
user's own stated fallback).

Story shown: complaint #1 (email, digiaim_group1@iimcal.ac.in) arrives with
no name/mobile → AI holds the ticket and asks → citizen replies with
details → ticket appears, confirmed, scored. Complaint #2 (WhatsApp, same
phone number, brand-new topic, no name/email given) → identity resolves
INSTANTLY and the ticket's Citizen Details show the email carried over from
complaint #1 automatically — this is the verified, real payoff (confirmed
both via direct API testing and by inspecting the actual recorded frame at
~105s: TKT-00052's citizen details show both digiaim_group1@iimcal.ac.in and
+919845011223 populated on a WhatsApp-origin ticket). Bonus flows also
shown: admin adds a live custom intake field and a fresh complaint
immediately asks for it; lead/agent ticket workflow with audit trail;
analytics close.

## Known limitation (disclosed to user)
Because several recording attempts were needed (see "what went wrong"
below) and the script is resumable-by-design (to avoid corrupting the
identity narrative on retry), the WhatsApp ticket used in the "agent
workflow" bonus scene (scene 11) had already been advanced to Resolved by
an earlier attempt's side effects. So scene 11 shows the final
already-resolved state with a real, accurate audit trail, rather than a
fresh live transition happening in that exact moment. The core ask (identity
resolution across channels) is unaffected and fully verified.

## Real side effect (disclosed to user)
digiaim_group1@iimcal.ac.in is a real address and EMAIL_SMTP_MOCK is not
set, so the AI's automatic acknowledgment/follow-up emails were genuinely
sent to that real inbox during testing/recording (confirmed via
scripts/api-gateway.log): 3 emails — two "Update on your message" and one
"Your complaint has been registered — Ticket TKT-00051". Not harmful, just
worth knowing. The fabricated "digiaim_group1_followup@iimcal.ac.in"
address used for the admin-cascade scene doesn't exist; any send attempts
to it simply fail/bounce silently.

## What went wrong along the way (for future reference / if redoing this)
1. Playwright's `recordVideo` context option is unreliable in this
   environment: silently produces NO file with the system Chrome channel;
   crashes the renderer with Playwright's bundled headless-shell build on
   this app's heavier pages. WORKAROUND USED: abandoned `recordVideo`
   entirely; capture frames manually via CDP screencast
   (`page.context().newCDPSession(page)` → `Page.startScreencast` /
   `Page.screencastFrame` / `Page.screencastFrameAck`), saving numbered
   JPEGs + an elapsed-ms manifest.
2. The dashboard's Next.js DEV SERVER crashed into a Jest-worker EPIPE loop
   partway through (a documented gotcha in this repo after heavy use) —
   looked exactly like a browser/login bug until `scripts/dashboard.log`
   was checked. Fixed by killing the port-3000 process and restarting
   `npm run dev` — no app code touched.
3. CDP screencast only emits a frame on repaint, so long static holds would
   freeze the video — fixed with a harmless net-zero mouse-wheel jiggle
   every ~400ms during waits to keep frames flowing.
4. A single global speed-up ratio (to match the video's real recorded
   length to the narration's total length) caused scene-by-scene drift,
   because scenes with page reloads/navigations have disproportionately
   more real overhead than pure-overlay scenes. Fixed by adding scene
   boundary markers (`mark(id)` in the recording script →
   `scenes_manifest.json`) and rescaling each scene's own frames to its own
   narration hold duration individually before one final ffmpeg concat pass
   (`assemble_video2.py`, NOT the earlier `assemble_video.py`).
5. Several run attempts were externally `killed` (not failed — no error,
   just terminated) when run via `run_in_background: true`, at
   increasingly early points. Root cause not fully diagnosed; worked around
   by running the final successful attempt in the FOREGROUND instead.

## Reusable artifacts (in `$CLAUDE_JOB_DIR/tmp`, may not survive a fresh job)
- `record_demo.js` — the 12-scene resumable recording script (CDP
  screencast, scene markers, resumability guards on scenes 3/5/7/10).
- `gen_narration.py` — Windows SAPI TTS generator (voice "Microsoft Ravi"),
  produces `narration/master_narration.wav` + `narration/manifest.json`.
- `assemble_video2.py` — the CORRECT assembly script (per-scene timing
  correction). `assemble_video.py` (global speed ratio) is superseded/buggy,
  kept only for reference.
- `frames/` — 1560 captured JPEGs + `frames_manifest.json` +
  `scenes_manifest.json` from the successful run.

## Standing state
Full stack running: gw 8080, dbw 8090, ai 8001 (OpenAI live), dashboard 3000
(RESTARTED once this session — fresh process, healthy), Memurai 6379.
Tenant `t1` intake-fields config now has: Mobile mandatory on Email (was
Optional), plus a "connectionType" custom field mandatory on Email (added
live during the recording's admin-cascade scene) — this is now the LIVE
config; revert via `PUT /api/v1/tenant/intake-fields` if the user wants
different defaults for their own testing going forward.
Logins unchanged: admin@tneb.demo/Admin@123, agent@tneb.demo/Agent@123,
lead@uniserv.com/Lead@1234.

Everything from the EARLIER deck/IMC-strategy task this session
(`UniServe_Product_Demo_v1.pptx`, `marketing/UniServe_IMC_Strategy.md`,
`marketing/UniServe_Digital_Campaign_Brief.md`) is complete and untouched by
this video work — see git status / repo root for those files.

Nothing has been committed to git or pushed this session (4 unpushed
commits predate this session; per earlier instruction the user pushes
manually due to an interactive credential prompt).
