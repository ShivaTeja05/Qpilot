# Parity: the three old pages → the one page

Before the old pages are deleted, every feature and every safety property they had is either
carried into the one page (a route, a screen, a test) or dropped on purpose. This file is the
checklist. Owner: **legacy** (docs/app.md §7). Rows are re-checked after each merge into
`ui/one-page`.

The old pages:

* **A**: `qpilot app`, the Gradio results page (`qpilot/app.py`, `qpilot/app_state.py`;
  tests `tests/app/`).
* **S**: `qpilot studio`, the Gradio Studio page (`qpilot/studio.py`, `qpilot/studio_state.py`;
  tests `tests/studio/test_studio_app.py`, `tests/studio/test_studio_demo_ui.py`).
* **Q**: `qsim app`, the robustness audit page (the stdlib HTTP handler in `sim/src/qsim/app.py`
  plus `sim/src/qsim/app_page.html`; tests `sim/tests/test_app.py`, the handler parts of
  `sim/tests/test_plates.py`).

Status words:

* **covered**: the route or screen exists and a test checks it (named).
* **built**: the route exists; its test is still to come (named owner).
* **planned**: written in docs/app.md or the owner's brief, not built yet.
* **MISSING (owner)**: in neither. Each one was posted to its owner on the bus. When a row is
  resolved, its status changes here.
* **dropped**: deliberately not carried over (the reason is given).

Parity tests written by legacy: `tests/web/test_parity_*.py`. Tests by other owners are named
by file. "Old test" names the test the row came from; **B** marks a behaviour test (portable to
HTTP), **G** a test of Gradio wiring only.

---

## 1. Safety properties (all three pages)

| # | Property | Old (page · test) | New: how it holds · test | Status |
|---|---|---|---|---|
| P1 | Every write from the page is `actor="human"`; the request cannot choose | A, S · A `test_decide_moves_on…` (B); S `test_every_handler_decides_only_on_a_click_and_only_as_human`, `test_the_source_passes_only_human_as_actor…` (G) | The server sets the actor; no request body has an `actor` field; a spoofed `"actor": "agent"` is ignored · `test_studio_flow.py::test_decisions_refuse_stale_and_settled`, `test_results_routes.py::test_decide_then_undo_writes_new_entries_as_a_person`; `test_parity_studio.py::test_the_web_code_writes_only_as_a_person` (AST scan of `qpilot/web/**`, with its own self-check `::test_the_actor_scan_catches_a_write_as_an_agent`), `::test_no_request_body_carries_an_actor` | covered |
| P2 | Reading never writes | S `test_reading_handlers_write_nothing` (G) | Every `GET` route of a session and of a study leaves the decision and proposal files byte-identical · `test_parity_studio.py::test_every_get_route_writes_nothing`, `test_parity_decisions.py::test_every_study_get_route_writes_nothing` (both enumerate the app's routes, so new ones are swept too) | covered |
| P3 | Blind until the design and the curves are both confirmed: nothing pairs a group with a number | S `test_nothing_of_the_analysis_is_read_or_shown_before_both_blind_stages`, `test_results_shown_once_both_blind_stages_are_confirmed_and_never_kept` (B) | 403 `blind` from the server · `test_studio_flow.py::test_blind_until_confirmed`, `test_results_routes.py::test_results_are_blind_again_when_the_design_changes`; `test_parity_studio.py::test_no_get_route_reveals_results_while_blind` (every session `GET`, job results, workspaces), `test_parity_decisions.py::test_a_study_blind_again_shows_and_does_nothing` (every study `GET` and `POST`, audit / Prism / record routes included as they land) | covered |
| P4 | A blind card says at most "this matters" | S `test_a_blind_card_says_at_most_that_it_matters` (B) | `studio_views.blind_kind`; `matters` answers yes / no / unknown only · `test_studio_flow.py::test_matters_answers_only_yes_or_no` | covered |
| P5 | "What the model saw" shows no result while blind | S `test_what_the_model_saw_shows_no_result_once_a_stage_is_blind_again` (B) | `GET /api/sessions/{sid}/model-seen` · `test_studio_flow.py::test_blind_until_confirmed` | covered |
| P6 | Stale heads: a write carries the head the view showed; anything newer → nothing written, the view re-reads | A `test_a_change_elsewhere_makes_the_card_stale`, `…is_flagged_even_when_nothing_is_written` (B); S `test_a_decision_on_a_changed_inbox_is_stale_and_writes_nothing` (B) | 409 `stale` + `details.head`. An agent's request never makes a person's decision stale (core `changed_since`); a request that arrived after the page looked makes its turn-down stale · `test_studio_flow.py::test_decisions_refuse_stale_and_settled`, `test_results_routes.py::test_decide_then_undo_writes_new_entries_as_a_person`, `test_parity_decisions.py::test_undo_and_turn_down_with_an_old_head_write_nothing` | covered |
| P7 | Bulk actions act on exactly the list shown | S `test_accept_all_consistent_lists_then_accepts_exactly_that_list`, `test_reject_all_lists_contradicted_ai_calls_and_needs_a_reason` (B) | `GET` then `POST /bulk/{action}` with the ids and `expected_head` (stronger than the old page, which sent no head) · `test_studio_flow.py::test_bulk_lists_are_exactly_what_is_acted_on` | covered |
| P8 | Reasons are required where the record needs one (reject, contradicted accept, exclusion, undo) and are at most 500 characters | A, S · S `test_reject_needs_a_reason…` (B) | 422 `bad_request` · `test_studio_flow.py::test_reject_needs_a_reason_and_edit_must_change_something`, `test_results_routes.py::test_decide_refuses_bad_requests` | covered |
| P9 | Undo is a new chain entry; only Undo can write the `Undo:` prefix | A `test_undo_steps_back_through_the_history`, `test_a_decide_reason_cannot_pose_as_an_undo` (B) | `qpilot/ai/suggest_only.py` `undo_target` · `test_parity_suggest_only.py::test_undo_steps_back_through_the_cards_own_history`, `test_results_routes.py::test_decide_then_undo_writes_new_entries_as_a_person` | covered |
| P10 | Suggest mode: the model may only ask (a request for a person, on every card) | A `test_ask_in_suggest_mode_only_asks_and_shows_the_request`, `test_decide_and_tell_applies_only_what_changes_no_conclusion` (B) | Stronger now (RT-UI-017, coordinator #0233, api-ops 7b4ff82): the page's Ask never writes, in any autonomy mode; it names the card and returns `focus: "card:<id>"`, and a person decides there. `SuggestOnlyStore` keeps the rule for the model · `test_parity_suggest_only.py`; `test_parity_decisions.py::test_ask_never_writes_and_leads_to_the_card` | covered |
| P11 | A choice that can change a conclusion always waits for a person, at every autonomy level | A `test_decide_and_tell_applies_only_what_changes_no_conclusion` (B) | `core.decisions` · `tests/ai/test_safety_regressions.py`, `test_ask.py::test_decide_and_tell_applies_only_what_changes_no_conclusion` | covered |
| P12 | Text is text: every string from a file, a sheet, a model or an agent reaches the screen as text | A `test_a_reason_with_markup_is_shown_as_text`, `test_a_hostile_label_from_an_rdml_file_is_shown_as_text`, `test_model_text_with_markup_is_escaped` (B); S `test_hostile_text_is_escaped_in_every_html_output` (G), `test_names_from_the_file_and_agent_text_are_escaped_with_the_real_service` (B); Q `esc()` in the page | The server sends JSON only (never HTML it builds from data), `nosniff`, CSP `default-src 'self'`; hostile names come back verbatim as data; React escapes; lint forbids `dangerouslySetInnerHTML` / `innerHTML` (`frontend/eslint.config.js`) · `test_parity_studio.py::test_hostile_names_come_back_as_data_in_json_only`; `test_guard.py::test_every_answer_carries_the_security_headers` | covered |
| P13 | Quarantined names shown as their quoted text; instruction-like text flagged and never obeyed | S `test_names_from_the_file_and_agent_text_are_escaped_with_the_real_service` (B) | `GET /api/sessions/{sid}/quarantine` (`instruction_like` flag) · `test_studio_flow.py::test_reading_routes_and_their_ids`; never obeyed: `tests/studio/test_service_gates.py`, `tests/core/test_firewall.py` | covered |
| P14 | This machine only: Host must be `127.0.0.1` / `localhost` | A, S `test_foreign_hosts_and_store_files_are_refused` (B); Q `_local()` | `security.Guard` (400) · `test_guard.py::test_other_host_names_are_refused` | covered |
| P15 | Writes from another site are refused (Q also refused cross-site GETs) | Q `_local()` Origin check (`test_plates.py::test_open_your_own_plate_endpoints`) | Origin / Referer check on writes (403 `cross_origin`); reads need this launch's key (HttpOnly, `SameSite=Strict` cookie), which no other site has · `test_guard.py::test_writes_from_another_site_are_refused`, `::test_api_needs_the_launch_key` | covered (stronger: a launch key) |
| P16 | Bound to 127.0.0.1, never shared, no server banner, no request log | A, S `test_launch_options_are_local_only`, `test_main_launches_with_every_hardening_option` (G) | `qpilot.web.server.main` → uvicorn on `127.0.0.1` · `test_parity_launch.py::test_main_serves_this_machine_only` | covered |
| P17 | No telemetry, no third-party pages, nothing loaded from the internet | A, S `test_telemetry_is_forced_off…` (G) | No Gradio; `docs_url=None`; CSP · `test_parity_suggest_only.py::test_the_helpers_load_without_gradio`; `test_guard.py::test_no_third_party_docs_pages`; e2e (built page: no external URLs) | covered |
| P18 | Works offline with no model (open, propose) | A `test_page_builds_and_opens_with_the_network_switched_off` (B); S `test_the_page_opens_and_proposes_with_the_network_switched_off` (B) | · `test_parity_launch.py::test_open_and_propose_with_the_network_switched_off` | covered |
| P19 | Files are served only from the build and from registered downloads; the study store and the dataset cache never | A, S `test_foreign_hosts_and_store_files_are_refused` (B); Q `RAW_FILES` whitelist (`test_http_endpoints`) | `server._static_file`; downloads only from `<store>/../exports/<workspace>/` (coordinator #0181, api-files); an audit's files only when its `AUDIT.sha256` lists them · `test_guard.py::test_static_files_never_leave_the_build`; `test_parity_launch.py::test_store_files_are_never_served`; `test_audit.py::test_a_file_the_audit_does_not_list_is_not_served`; downloads: `test_record*.py` (api-files) | covered (static, audit) · planned (downloads: api-files) |
| P20 | Upload cap (200 MB RDML; Q 32 MiB) enforced while the body streams | A, S Gradio `max_file_size="200mb"` (G); Q `test_plates.py` 413 before reading | `Guard` checks `Content-Length` and counts a chunked body as it streams (api 4cf1f9d) · `test_parity_launch.py::test_an_upload_over_the_cap_is_refused`, `::test_a_chunked_upload_over_the_cap_is_refused_while_it_streams` | covered |
| P21 | Errors are sentences, never a traceback (`show_error=False`) | A, S launch options (G); Q JSON `{"error"}` | `ApiError` JSON for every refusal; an unexpected exception → Starlette's plain `Internal Server Error` · `test_parity_launch.py::test_an_unexpected_error_leaks_no_traceback`, `::test_an_unexpected_error_is_a_sentence_with_the_security_headers` (xfail strict: PARITY-2) | covered (no traceback) · **MISSING (api)**: that 500 is plain text, outside the `{"error"}` shape and without the security headers (PARITY-2) |
| P22 | The API key is never shown; it goes only with the configuration it was set for; a missing key is reported by name | A `test_the_api_key_only_goes_where_it_was_configured`, `test_a_missing_key_is_reported_not_hidden` (B) | The model comes from the environment only: no route sets a provider or an endpoint · `test_parity_launch.py::test_the_page_cannot_choose_a_model_endpoint`, `::test_the_api_key_is_never_shown`, `::test_a_missing_key_is_reported_by_name` | covered |
| P23 | A broken model profile does not stop the page | A `test_a_broken_profile_does_not_stop_the_app` (B) | `load_profile_or_default` · `test_parity_launch.py::test_a_broken_profile_does_not_stop_the_server` | covered |
| P24 | One slow job at a time per kind (Analyse ≤ 2, Check model 1, Open/Propose/Send 1) | A, S Gradio `concurrency_limit` (G); Q `_job_lock` → 409 | `qpilot.web.jobs.JobRunner` | built (redteam: job flooding) |
| P25 | Bounded JSON bodies (Q: 64 KiB) | Q `do_POST` | Only the 200 MB upload cap applies to every write | **MISSING (api)**: a JSON write can be up to 200 MB (PARITY-3, low) |
| P26 | The page's own action never makes its next write stale | A `test_decide_right_after_ask_is_not_stale` (B) | Ask writes nothing (RT-UI-017), so the head the page had stays good · `test_parity_decisions.py::test_ask_never_writes_and_leads_to_the_card` | covered |
| P27 | A model status check reaches out only when a person asks (A pinged on "Check connection" only; S pinged in the background) | A `on_connect` | Coordinator (#0180): `GET /api/model` never contacts a REMOTE model (configuration + last known answer); a click sends `POST /api/model/check`; a LOCAL endpoint may keep the background ping · `test_parity_launch.py::test_reading_the_model_status_never_calls_a_remote_model` (xfail strict: PARITY-4) | **MISSING (api)**: today `GET /api/model` pings a configured remote model (PARITY-4) |

## 2. A: `qpilot app` (Gradio results page)

| # | Feature | Old test | New: route · screen · test | Status |
|---|---|---|---|---|
| A1 | Open a study: the demo, an uploaded RDML, or a study already in the store | `test_open_shows_the_first_card_summary_and_meter` (B) | `GET /api/workspaces`, `POST /api/workspaces`, `/workspaces/demo` · Open (home) · `test_workspaces.py`, `test_studio_flow.py` | covered. Changed on purpose: an uploaded file now starts a blind Studio session; a study analysed outside one (`qpilot run`, an agent) shows results at once (`#/r/…`) |
| A2 | Analysis failure and empty-store messages in words | none | Job `failed` with a sentence; Open's empty state (home) | built (home) |
| A3 | Study summary: plates · samples, the design sentence, the conclusion rule | `test_summary_and_rule` (B) | `GET /api/studies/{id}/results` summary (`design_line`, the rule) · Results summary strip (insight) · `test_results_routes.py::test_results_say_what_the_study_found` | built (api) · planned (insight) |
| A3a | The design sentence keeps its caveat: "Expression-defined, not a clinical call." | `test_summary_and_rule` (B) | `design_line` in the results summary (`app_state.design_line`, kept) · Results summary strip | built (api) · insight asked to show it (#0138) |
| A4 | Robustness meter (holds, fragile below 80 %) | `test_meter_rows_and_html` (B) | `/results` genes with robustness · robustness map (insight) · `test_results_routes.py`, `test_results_demo.py` | built (api) · planned (insight) |
| A5 | Confidence badge with named reasons (ordinal, never a percentage) | `test_confidence_badge_lists_reasons`, `test_confidence_phrasing_follows_fragility` (B) | `/results`, `/genes/{gene}` · Results table, Gene header | built (api) · planned (insight, gene) |
| A6 | All-genes table (gene, fold, CI, p, conclusion, holds, confidence) | `test_results_table` (B) | `/results` genes · Results "All genes" table (insight) · `test_results_demo.py::test_the_demo_results` | built (api) · planned (insight) |
| A7 | Decision counter: "N decisions could change a conclusion · M made automatically" | `test_card_order_counter_and_next` (B) | `/cards` `counter` (`app_state.decision_counter`) · Results Decision Cards header | built (api) · insight asked to show it (#0138) |
| A8 | Decision Card: options with what each changes per headline gene, recommended / chosen / "not recommended (MIQE)" tags, impact line, status line | `test_refset_card_view_shows_the_flip`, `test_auto_decided_card_says_so_once`, `test_zero_flips_is_said_in_words` (B) | `GET /api/studies/{id}/cards`, `…/cards/{card_id}` · Decision Cards (insight) · `test_results_routes.py`, `test_results_demo.py::test_flip_matrix_matches_the_cards` | built (api) · planned (insight) |
| A9 | Cards in rank order; the first open (or pending) card first; "every choice is decided: export the record" | `test_card_order_counter_and_next` (B) | `/cards` in rank order; `DecisionDone.next_card` and its message; `WorkspaceView.next_step` | built (api) · planned (insight) |
| A10 | geNorm chart on the reference-set card (M per gene, the usual cut-off) | none | `/results` reference genes (M, V, order, `cutoff_m`, stable) · `GenormBars` (`@/charts`) on Results / Gene | built (api) · planned (insight, gene) |
| A11 | Decide (option + reason, as a person, with the head) | `test_decide_moves_on_clears_the_reason_and_logs_a_human_entry` (B) | `POST /api/studies/{id}/cards/{card_id}/decide` · `test_results_routes.py::test_decide_then_undo_writes_new_entries_as_a_person` | covered (API) · planned (insight) |
| A12 | Undo ("Undo: back to …", reason required, a new entry) | `test_undo_steps_back_through_the_history` (B) | `POST …/cards/{card_id}/undo` · `test_results_routes.py::test_decide_then_undo_writes_new_entries_as_a_person` | covered (API) · planned (insight) |
| A13 | Turn down an agent's request (reason, head); the requested option is named | `test_ask_in_suggest_mode_only_asks_and_shows_the_request` (B) | `POST …/cards/{card_id}/reject-request`; `GET /api/agents` · `test_results_routes.py::test_an_agents_request_waits_and_can_be_turned_down`, `test_agents.py` | covered (API) · planned (insight, record) |
| A14 | Only the current card's options are accepted | `test_a_value_from_an_old_card_is_refused_by_the_page` (G) | 422 "Unknown option" · `test_results_routes.py::test_decide_refuses_bad_requests` | covered |
| A15 | Explain with the model (template fallback, the reason the model was not used, numbers as cited facts) | `test_explain_and_seen_without_a_model`, `test_model_text_with_markup_is_escaped` (B) | `POST …/cards/{card_id}/explain` (job; 409 `no_model` without one) · `test_results_routes.py::test_explain_needs_a_model` | covered (API) · planned (insight) |
| A15a | Each Explain call is logged with the study (`store.append_ai_call`), so the record carries it | none | The explain job appends the log line · `test_parity_decisions.py::test_each_explanation_is_logged_with_the_study` | covered |
| A16 | Ask your data (autonomy honoured; template fallback said; a request waits for you) | `test_ask_in_suggest_mode_only_asks_and_shows_the_request`, `test_decide_right_after_ask_is_not_stale` (B) | `POST /api/studies/{id}/ask` (never writes: RT-UI-017) · `test_ask.py`, `test_ask_audit.py` · Ask drawer (ask) | covered (API) · planned (ask) |
| A16a | When Ask turns into a request (Suggest mode), the answer says it waits for a person and leads to the card | `test_ask_in_suggest_mode_only_asks_and_shows_the_request` (B) | Now: the answer says what the card is ("Decide … on its Decision Card") and returns `focus: "card:<id>"`; the page focuses that card (ask: `useFocusTarget`) · `test_parity_decisions.py::test_ask_never_writes_and_leads_to_the_card` | covered (API) · planned (ask) |
| A17 | What the model sees (the last payload) | `test_explain_and_seen_without_a_model`, `test_changing_the_model_clears_what_the_model_sees` (B) | `GET /api/model/seen` (blind-gated) · `test_ask_model.py::test_nothing_was_sent_yet`, `::test_a_payload_that_may_hold_results_is_hidden_while_a_session_is_blind` · Ask drawer fold-out | covered (API) · planned (ask) |
| A18 | Model provider, endpoint and name typed on the page | `test_the_model_selector_starts_from_the_environment` (B) | — | dropped: the model comes from the environment only (docs/app.md §4 Settings). P22 checks the page cannot set one |
| A19 | Check connection (green / grey / red with the reason) | none | `GET /api/model` (configuration + last known answer); `POST /api/model/check` for a click (api, per #0180) · Settings (home), top-bar chip (shell) | built (status) · planned (check: api) |
| A20 | Check this model (harness scorecard, saved by profile) | `test_check_model_with_no_model_scores_templates` (B) | `POST /api/model/test` (job) · `test_ask_model.py::test_the_model_test_scores_templates_and_saves_the_scorecard` · Settings | covered (API) · planned (home) |
| A21 | Autonomy: Suggest / Decide and tell me, with the policy lines | `test_policy_and_footer` (B) | `GET/PUT /api/settings`, `/api/system` policy · Settings, top bar | built (home, shell) |
| A22 | Export the Analysis Record (one zip that verifies) | `test_export_writes_one_zip_that_verifies_and_warns_about_open_choices` (B) | `POST /api/studies/{id}/record` (api-files) · Record | planned |
| A22a | The export says how many conclusion-changing choices are still open, and when something was decided after the view was loaded | same | Export result `open_flips`, `head_moved` (with `expected_head`), `warnings` in the old words (api-files #0169) · Record | planned (api-files, record) |
| A23 | Never-does lines and the version (footer) | `test_policy_and_footer` (B) | `GET /api/system` `never` · Settings · `test_workspaces.py::test_system_says_what_this_install_is` | covered |
| A24 | Start a fresh demo (moves earlier work aside, never deletes) | `test_fresh_demo_moves_earlier_decisions_aside` (B) | `POST /api/demo/fresh` · `test_ask_model.py::test_a_fresh_demo_moves_the_demo_aside_and_keeps_it` · Settings | covered (API) · planned (home) |
| A25 | `qpilot doctor` (outbound line, key set or not) | `test_doctor_*` (B) | CLI, unchanged | covered (the tests stay; they move out of `tests/app/` at removal) |
| A26 | Explain templates, facts, no naked numbers | `tests/app/test_templates.py` (B) | `qpilot.explain` (not a page) | covered (the tests stay) |
| A27 | Card picker; "picking the current card changes nothing" | `test_picking_the_current_card_changes_nothing` (G) | Cards list with `j`/`k` | dropped (Gradio state detail) |

## 3. S: `qpilot studio` (Gradio Studio page)

| # | Feature | Old test | New: route · screen · test | Status |
|---|---|---|---|---|
| S1 | Open an RDML (+ optional sample sheet), suffix checked, kept by SHA-256, not served | none (no old test uploads) | `POST /api/workspaces` · Open · `test_workspaces.py::test_opening_a_file_starts_a_session`, `::test_a_file_of_the_wrong_kind_is_refused` | covered |
| S2 | One sentence about the experiment (≤ 500), used by Propose the design, quarantined as data | `test_the_page_opens_and_proposes…` (B) | Form field `sentence` (`max_length`) | built (home, design) |
| S3 | Reopening a file continues its session | D3 (B) | Session id = `input_sha256[:12]`; hash routes `#/s/<sid>/…` | built |
| S4 | File facts (samples by type, targets, plates, sheet cells) | `test_hostile_text_is_escaped…` (G) | `WorkspaceView.file` · Design | built (design) |
| S5 | Stage strip with blockers and counts waiting | D3 (B) | `WorkspaceView.stages` · the rail (shell) | built (shell) |
| S6 | Propose the design (rules, then the model; refusals said) | D4 (B) | `POST /api/sessions/{sid}/propose/design` · `test_studio_flow.py::test_proposing_writes_as_the_system_and_says_so` | covered |
| S7 | Propose the comparison | `test_confirm_shows_what_it_covers…` (B) | `POST …/propose/comparison` · `test_studio_flow.py::test_the_whole_walk_over_http` | covered |
| S8 | Check the curves (Curve Judge; well calls; the call rule) | D4 (B) | `POST …/propose/curves` · `test_studio_flow.py` | covered |
| S9 | The six-part proposal card (proposal + alternatives, Why, engine check, consequence, level, actions, made by) | `test_names_from_the_file…` (B) | `GET …/proposals`, `…/proposals/{pid}`, `…/quarantine` · `ProposalCard` (design) | built (design) |
| S10 | Accept / Edit / Reject (reasons, contradicted needs a reason, edits change payload fields only) | `test_edit_goes_through_the_service_as_the_persons_edit`, `test_reject_needs_a_reason…` (B) | `POST …/proposals/{pid}/accept|edit|reject` · `test_studio_flow.py::test_an_agent_proposal_can_be_edited_and_accepted`, `::test_reject_needs_a_reason_and_edit_must_change_something` | covered |
| S11 | Does this matter? (yes / no / cannot tell; dropped once the chain moves) | `test_a_does_this_matter_answer_is_dropped_once_the_chain_moves_on` (B) | `POST …/proposals/{pid}/matters` (the answer carries its head) · `test_studio_flow.py::test_matters_answers_only_yes_or_no`; dropping a stale answer: design | covered (API) · built (design) |
| S12 | Accept all consistent… / Reject contradicted AI calls… (exact list first) | `test_accept_all_consistent…`, `test_reject_all_lists_contradicted…` (B) | `GET/POST …/bulk/{action}` · `test_studio_flow.py::test_bulk_lists_are_exactly_what_is_acted_on` | covered |
| S13 | Confirm this stage… (what it covers, then Yes, confirm; refused while proposals wait; a changed stage is not confirmed) | `test_confirm_shows_what_it_covers_and_only_the_second_click_confirms` (B) | `GET/POST …/confirm/{stage}`, `…/confirm/{stage}/accept` · `test_studio_flow.py::test_confirm_refuses_while_the_stage_is_open` | covered |
| S14 | "Not yet" (turn down a confirm, with a reason) | none (only in sweeps) | Reject the `stage.confirm` proposal (`…/proposals/{pid}/reject`) | built (design) |
| S15 | Decided in this stage (status, what, reason) | none | `GET …/proposals?stage=` returns decided ones too | **MISSING (design)**: the Design brief and docs/app.md §4 do not show the decided list |
| S16 | Inbox order (contradicted → cannot check → consistent), paging | `test_names_from_the_file…` (B) | Inbox order (design); paging dropped for a virtualised list | built (design) |
| S17 | Curve of a cited well | `test_the_curve_of_a_cited_well_is_drawn` (B) | `GET …/curve?well=` · Curves viewer (curves) · `test_studio_flow.py::test_reading_routes_and_their_ids` | covered |
| S18 | Model status line (none / local / REMOTE names pseudonymised / checking / not answering + reason) | none | `GET /api/model` · top-bar chip (shell) | built (shell) |
| S19 | What the model saw (the last call; blind-gated) | `test_what_the_model_saw…`, `test_the_seen_panel_stays_closed_until_asked_for` (B, G) | `GET …/model-seen` · design / ask | covered (API) |
| S20 | Results once both blind stages are confirmed (summary, meter, "Analysis <id>") | `test_results_shown_once_both_blind_stages_are_confirmed_and_never_kept` (B) | `ensure_analysis` job after the curves confirm; Results | covered (API: `test_the_whole_walk_over_http`) · planned (Results: api, insight) |
| S21 | Decision Cards in Studio (Choices) and the moved-analysis message after an exclusion | D3 (B) | Results Decision Cards (same as A8–A13) | planned (api, insight) |
| S22 | Confirm the analysis choices (the Choices stage) | D3 (B) | — | open question #0097 (prism → coordinator, insight) |
| S23 | Why the bridge matters: how often the usual Excel→Prism routes change a conclusion | D1, D4 (B) | `GET …/prism/routes` (api-files) · Prism | planned |
| S24 | Prism preview (test, graph, layout, template, groups, references, tables, exported choices with who decided, caption) and a per-gene graph | `test_results_shown…` (B) | `GET …/prism/preview` (api-files) · Prism | planned |
| S25 | Draft the Prism project (a proposal, accepted like any other) | D3 (B) | `POST …/prism/draft` (api-files) · Prism | planned |
| S26 | Send to Prism (bundle in the exports folder; launch if installed; else the command and a zip) | D3 (B) | `POST …/prism/send` (api-files; bundles under `<store>/../exports/<workspace>/`, #0181) · Prism | planned |
| S27 | Round trip (this page's bundles only; the sent-back folder inside exports or home, never a link, never the store) | `test_a_sent_back_folder_outside_the_export_and_home_folders_is_refused` (B) | `POST …/prism/roundtrip` + `qpilot/web/folders.py` (api-files) · `test_prism*.py` | planned |
| S28 | Round-trip questions: what all exclusions do together; stale questions show no numbers and are refused | `test_the_round_trip_says_what_all_exclusions_do_together_and_marks_stale_cards` (B) | Round-trip job result + proposals (api-files, prism) | planned |
| S29 | Next-step guidance on every stage | D3, D4 (B) | `WorkspaceView.next_step` · banner (shell) | built |
| S30 | `qpilot studio` serves the page; `qpilot studio demo --check` | `test_the_cli_studio_command_is_registered` (B); D1, D2 (B) | `qpilot studio` serves the one page (api-ops 81311e4) · `test_cli_one_page.py::test_qpilot_studio_opens_the_one_page_and_says_so`, `::test_qpilot_studio_demo_still_needs_check`; D1, D2 stay | covered |
| S31 | Page actions are not published as an API | `test_the_page_actions_are_not_published_as_api_endpoints` (G) | — | dropped: the API is the page's interface, behind the launch key (P15) |
| S32 | Plate map | none (S had no plate grid) | `GET …/plate` · plate map (curves, design) | new |

## 4. Q: `qsim app` (the audit page)

The views stay in `qsim.app.Screen` / `qsim.app_lab.LabViews`; the API serves them (api-audit),
so the Screen behaviour tests in `sim/tests/test_app.py` stay. Only the stdlib handler, `serve`
and `app_page.html` go.

| # | Feature | Old test | New: route · screen · test | Status |
|---|---|---|---|---|
| Q1 | Study line and verdict counts | `test_counts_match_the_engine_files` (B) | `GET …/audit`, `…/audit/overview` · `test_audit.py::test_a_ready_audit_says_what_it_audited`, `::test_every_view_is_the_screens_own_dict` · Audit Study tab | covered (API) · planned (audit) |
| Q2 | Gene card: verdict, headline, tiles; what changes it / leans on / what to do | `test_card_numbers_come_from_explain_json` (B) | `GET …/audit/gene/{g}` · `test_audit.py::test_every_gene_has_every_view`, `::test_call_keys_say_what_the_words_say` · Gene | covered (API) · planned (gene) |
| Q3 | Every reasonable analysis (dot strip) | `test_live_analyses_reproduce_the_run` (B) | `GET …/audit/analyses/{g}` · `test_audit.py::test_the_live_views_are_the_audited_analysis` · Gene (`AnalysesStrip`) | covered (API) · planned (gene) |
| Q4 | One choice at a time | `test_samples_and_choices_match_the_engine` (B) | `GET …/audit/effects/{g}` · `test_audit.py::test_every_gene_has_every_view` · Gene (`ChoiceDotPlot`) | covered (API) · planned (gene) |
| Q5 | Your samples (follows the what-if choices) | `test_samples_and_choices_match_the_engine` (B) | `POST …/audit/samples` · `test_audit.py::test_samples_follow_the_choices` · Gene (`Beeswarm`) | covered (API) · planned (gene) |
| Q6 | Assay and wells; reference genes | `test_http_endpoints` (B) | `GET …/audit/lab/{g}` · `test_audit.py::test_lab_numbers_are_the_worded_rows` · Gene | covered (API) · planned (gene) |
| Q7 | Study map, calls changed by one choice, share of spread, reference stability, fix these first, what to check first | `test_http_endpoints` (B) | `GET …/audit/study`, `…/audit/issues` · `test_audit.py::test_every_view_is_the_screens_own_dict`, `::test_the_whole_issue_queue` · Audit Study tab | covered (API) · planned (audit) |
| Q8 | What-if lab (selects by tier, planned marked, reset, changed/all toggle, live dumbbell) | `test_whatif_matches_the_engine` (B) | `POST …/audit/whatif` · `test_audit.py::test_whatif_changes_a_call_as_one_choice_at_a_time_says`, `::test_whatif_with_no_change_changes_nothing`, `::test_concurrent_whatifs_answer_as_if_alone` · Audit What-if lab | covered (API) · planned (audit) |
| Q9 | How it works (stages, verdict rules, known answers, limits) | `test_http_endpoints` (B) | `GET …/audit/how` · `test_audit.py::test_every_view_is_the_screens_own_dict` · Audit How it works | covered (API) · planned (audit) |
| Q10 | Ask (the audit's Asker: tool, who wrote the words, facts) | `test_http_endpoints` (B) | `POST /api/studies/{id}/ask` (the audit answers verdict and what-if questions) · `test_ask_audit.py` · Ask drawer | covered (API) · planned (ask) |
| Q11 | Gene search, verdict filter chips, gene list, `#gene=` links | none | Results table filters; `…/gene/<GENE>` routes | planned (insight, gene, shell) |
| Q12 | Unknown gene → 404; unknown decision or option → 400 (LabViews raises `ValueError` for an unknown gene: the API must check first) | `test_http_endpoints`, `test_whatif_matches_the_engine` (B) | Membership checked first; 404 / 422 in words · `test_audit.py::test_a_gene_outside_the_audit_is_not_found`, `::test_whatif_refuses_unknown_choices_in_words` | covered |
| Q13 | No statistics jargon in any view; no hand-typed numbers in the page markup | `test_no_statistics_jargon_on_any_screen` (B), `test_page_markup_types_no_numbers` (B) | The Screen views keep their test; the page: §1.3 "no mock data" (redteam, e2e) | covered (views) · planned (page) |
| Q14 | Provenance: run hash, lock sha, input sha, version | none | `POST …/audit/verify` (checksums, binding to the record) · `test_audit.py::test_the_audit_verifies_and_is_bound_to_the_studys_record`, `::test_a_changed_audit_file_fails_verification` · Audit Verify tab | covered (API) · planned (audit) |
| Q15 | Download the audit's raw files (`summary.json`, `explain.json`, `genes.csv`, …; a whitelist) | `test_http_endpoints` (B) | `GET …/audit/files`, `…/audit/files/{name}` (only files in the audit's `AUDIT.sha256`) · `test_audit.py::test_the_audits_files_can_be_listed_and_downloaded`, `::test_a_file_the_audit_does_not_list_is_not_served` · Audit Verify tab | covered (API) · planned (audit) |
| Q16 | Evidence page per gene (`/evidence/{g}`, server-rendered, printable) | `test_http_endpoints` (B) | Gene section | dropped: replaced by the Gene section (no server-rendered HTML) |
| Q17 | Copy a gene's summary to the clipboard | none | Gene header "Copy summary" (gene 518b8f8, #0154) | built (gene; not merged yet) |
| Q18 | Open your own plate (upload, progress, reopen, failure kept the screen) | `test_plates.py::test_open_your_own_plate_endpoints` | Open (upload → session) + Run the audit (job) | dropped: replaced by Open and the audit job; the safety rows (P14, P15, P20) carry |
| Q19 | `qsim app --results DIR` | none | `qsim app --results DIR` serves the one page with that run attached; `qpilot app --audit DIR` · `test_cli_one_page.py::test_qsim_app_serves_the_one_page_with_the_run_attached`, `::test_qpilot_app_attaches_audit_folders` | covered |

## 5. Removal notes (step 4, after "remove now")

* Keep: `qsim.app.Screen` and everything it needs (`RAW_FILES`, wording tables, helpers),
  `qsim.app_lab.LabViews`. Delete: `HOST`, `PAGE`, `Busy`, `App`, `make_handler`, `serve`,
  `_known` (port its gene check, Q12), `app_page.html`. `sim/src/qsim/cli.py` (api-ops) must stop
  importing `serve` first; `sim/tests/test_plates.py::test_open_your_own_plate_endpoints` uses
  `App` / `make_handler` and goes with them. `frontend/src/test/recorded/record.py` (insight)
  builds a `Screen` by hand and keeps working.
* `qpilot/app_state.py` is Gradio-free; `qpilot/web/routers/system.py` imports its `FOOTER`
  and `tests/engine/test_groups_wording.py` imports it too: keep what is still imported, or move
  it, before deleting.
* `tests/ai/test_safety_regressions.py` imports `SuggestOnlyStore` from `qpilot.app`; it must
  import from `qpilot.ai.suggest_only` before `qpilot/app.py` goes.
* Tests that stay (not about the page): `test_doctor_*`, `test_example_profile_loads`,
  `tests/app/test_templates.py`, `tests/app/test_smoke.py` (if it is not about the page),
  `test_studio_demo_ui.py` D1 and D2 (CLI).
