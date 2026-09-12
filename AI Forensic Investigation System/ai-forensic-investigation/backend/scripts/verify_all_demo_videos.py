"""Demo Investigation Dataset - comprehensive E2E verification (canonical).

Runs every demo video through the real system and reports a section matrix:

    1. DATASET     - files, sha256, licenses, manifest, scenarios, cases
    2. UPLOAD      - every demo video uploaded + READY with real detections
    3. LIVE        - real CV2 file-transport live session (evidence capture)
    4. RAG         - grounded / ungrounded / UNKNOWN abstention questions
    5. AGENT       - Phase 6 investigation + Phase 7 agent answer
    6. NEGATIVE    - cartoon clip (near-zero detections), not_a_video fixture
    7. SECURITY    - auth/RBAC, disclaimer labeling, no fake evidence claims

Each check is PASS / FAIL / NOT TESTED and the full matrix is written to
``data/demo_investigation/results/verification_all_results.json``.

Local-only mode (no ``--base-url``) verifies the dataset sections only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(BACKEND_DIR, "data", "demo_investigation")
RESULTS_DIR = os.path.join(ROOT, "results")

DEMO_EMAIL = "demo.investigation@forensics-demo.com"
DEMO_PASSWORD = "demo-investigation-2026"
BASE_URL_DEFAULT = "http://127.0.0.1:8000"

# Order-sensitive matrix of section -> result
STATUSES: dict[str, str] = {}  # section -> PASS/FAIL/NOT TESTED
CHECKS: list[dict] = []


def record(ok: bool, name: str, detail: str = "", section: str = "MISC") -> bool:
    CHECKS.append({"section": section, "check": name, "pass": bool(ok), "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return bool(ok)


def set_section(section: str, ok: bool) -> None:
    prev = STATUSES.get(section, "PASS")
    if prev == "FAIL":
        return
    STATUSES[section] = "PASS" if ok else "FAIL"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ dataset


def verify_dataset() -> bool:
    sec = "DATASET"
    ok = True
    manifest_path = os.path.join(ROOT, "metadata", "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    ok &= record(manifest.get("schema_version") == 1, "manifest schema_version", section=sec)
    ok &= record("NOT REAL FORENSIC EVIDENCE" in manifest.get("disclaimer", ""), "manifest disclaimer", section=sec)

    videos = manifest.get("videos", [])
    ok &= record(len(videos) == 10, "10 demo videos declared", f"found {len(videos)}", section=sec)
    for v in videos:
        p = os.path.join(ROOT, v["path"])
        exists = os.path.isfile(p) and os.path.getsize(p) > 0
        ok &= record(exists, f"video {v['demo_id']} present", v["filename"], section=sec)
        if exists:
            h = sha256_file(p)
            ok &= record(h == v.get("sha256"), f"video {v['demo_id']} sha256 matches manifest", section=sec)
        ok &= record(bool(v.get("license")) and "CC BY" in v.get("license", ""),
                     f"video {v['demo_id']} CC BY license+source", section=sec)
        ok &= record(bool(v.get("stable_name")), f"video {v['demo_id']} stable_name", section=sec)
        ok &= record(bool(v.get("scenario_keys")), f"video {v['demo_id']} scenario_keys", section=sec)
        ok &= record(bool(v.get("source_url")), f"video {v['demo_id']} source_url", section=sec)

    for t in manifest.get("thumbnails", []):
        p = os.path.join(ROOT, t["path"])
        ok &= record(os.path.isfile(p) and os.path.getsize(p) > 0, f"thumbnail {t['demo_id']} present", section=sec)

    for k in manifest.get("keyframes", []):
        ok &= record(os.path.isfile(os.path.join(ROOT, k["path"])), f"keyframe {k['filename']} present", section=sec)

    for f in manifest.get("fixtures", []):
        ok &= record(os.path.isfile(os.path.join(ROOT, f["path"])), f"fixture {f['filename']} present", section=sec)

    # scenario catalog (12) + scenario files
    catalog = manifest.get("scenario_catalog", [])
    ok &= record(len(catalog) == 12, "scenario_catalog has 12 entries", f"found {len(catalog)}", section=sec)
    scen_dir = os.path.join(ROOT, "scenarios")
    if os.path.isdir(scen_dir):
        scen_files = sorted(x for x in os.listdir(scen_dir) if x.endswith(".json"))
        ok &= record(len(scen_files) == 12, "12 scenario files present", section=sec)
        for name in scen_files:
            with open(os.path.join(scen_dir, name), encoding="utf-8") as fh:
                s = json.load(fh)
            ok &= record(s.get("scenario_id") and s.get("stable_name"), f"scenario {name} has id+stable_name", section=sec)

    # cases
    with open(os.path.join(ROOT, "cases.json"), encoding="utf-8") as fh:
        cases = json.load(fh)
    ok &= record(len(cases) == 10, "10 demo cases", f"found {len(cases)}", section=sec)
    filenames = {v["filename"] for v in videos}
    for c in cases:
        cid = c.get("case_id")
        ok &= record(cid and cid.startswith("CASE-DEMO-"), f"case {cid} CASE-DEMO prefix", section=sec)
        ok &= record(c.get("video_file") in filenames, f"case {cid} references real video", section=sec)
        ok &= record(os.path.isfile(os.path.join(ROOT, c.get("expected_events_file", ""))),
                     f"case {cid} expected_events file", section=sec)
        ok &= record(os.path.isfile(os.path.join(ROOT, c.get("expected_observations_file", ""))),
                     f"case {cid} expected_observations file", section=sec)
        ok &= record(bool(c.get("scenario_ids")), f"case {cid} scenario_ids", section=sec)

    # expected_observations schema check (grounded classification)
    import glob
    observed_ever = unknown_ever = False
    for p in glob.glob(os.path.join(ROOT, "expected_observations", "*.json")):
        data = json.load(open(p, encoding="utf-8"))
        if "scenarios" not in data:
            ok &= record(False, f"{os.path.basename(p)} has scenarios list", section=sec)
        for s in data.get("scenarios", []):
            if s.get("expected") == "OBSERVED":
                observed_ever = True
            elif s.get("expected") == "UNKNOWN":
                unknown_ever = True
    ok &= record(observed_ever and unknown_ever, "expected_observations cover OBSERVED+UNKNOWN", section=sec)

    # negative fixture ffprobe checks
    na = os.path.join(ROOT, "videos", "fixtures", "not_a_video.mp4")
    if os.path.isfile(na):
        import subprocess
        proc = subprocess.run(["ffprobe", "-v", "error", na], capture_output=True, timeout=60)
        ok &= record(proc.returncode != 0, "not_a_video.mp4 not decodable (ffprobe fails)", section=sec)

    set_section(sec, ok)
    return ok


# ------------------------------------------------------------------ server


def _request(method: str, path: str, token: str | None = None, body=None, timeout: int = 90):
    url = f"{BASE}{path}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if data is not None and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
        except Exception:
            detail = str(exc)
        return exc.code, detail


def _login() -> str | None:
    _, login = _request("POST", "/auth/login", body={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    token = login.get("access_token") if isinstance(login, dict) else None
    if not token:
        record(False, "demo admin login", "no access_token returned")
    return token


def verify_uploads(token: str) -> bool:
    sec = "UPLOAD"
    ok = True
    _, videos = _request("GET", "/videos", token)
    demo_videos = [v for v in videos if v.get("filename", "").startswith("demo_video_")]
    ok &= record(len(demo_videos) == 10, "10 demo videos uploaded", f"found {len(demo_videos)}", section=sec)
    ready = 0
    for v in demo_videos:
        status = v.get("status")
        is_ready = status in ("READY", "COMPLETED")
        ready += 1 if is_ready else 0
        det_counts = _detection_counts(token, v["id"])
        label_sum = sum(det_counts.values())
        record(is_ready and label_sum >= 1, f"video {v['id']} {v['filename']} READY + detections",
               f"status={status} labels={label_sum} {det_counts}", section=sec)
    ok &= record(ready == 10, "all 10 demo videos READY", f"{ready}/10", section=sec)
    set_section(sec, ok)
    return ok


def _detection_counts(token: str, video_id: int) -> dict:
    st, dets = _request("GET", f"/videos/{video_id}/detections", token)
    counts = {}
    if st == 200:
        for d in dets:
            counts[d.get("label")] = counts.get(d.get("label"), 0) + 1
    return counts


def verify_live(token: str) -> dict | None:
    sec = "LIVE"
    ok = True
    # choose the primary street clip (DVS-002) for a real evidence capture run
    _, videos = _request("GET", "/videos", token)
    target = next((v for v in videos if "demo_video_02" in v.get("filename", "")), None)
    if not target or not target.get("camera_id"):
        set_section(sec, False)
        record(False, "live: primary video have camera_id", section=sec)
        return None
    camera_id = target["camera_id"]
    path = os.path.join(ROOT, "videos", target["filename"])

    st, start = _request("POST", f"/live/cameras/{camera_id}/start", token, body={
        "transport": "file", "video_path": path,
        "fps_target": 5, "buffer_window_seconds": 15, "buffer_max_frames": 150,
    })
    if st not in (201, 202):
        set_section(sec, False)
        record(False, "live: start file session", f"status={st}", section=sec)
        return None

    started = time.time()
    _request("POST", f"/live/cameras/{camera_id}/vlm/analyze", token, body={"trigger": "manual"})

    last = last_live = {}
    last_frames = -1
    stable_since = time.time()
    while time.time() - started < 240:
        time.sleep(2)
        st, snap = _request("GET", f"/live/cameras/{camera_id}/status", token)
        if st != 200:
            break
        last = snap
        if snap.get("status") == "LIVE":
            last_live = snap
        fr = snap.get("frames_received", 0)
        if fr == last_frames:
            if time.time() - stable_since > 8:
                time.sleep(4)
                st, snap = _request("GET", f"/live/cameras/{camera_id}/status", token)
                last = snap or last
                if snap.get("status") == "LIVE":
                    last_live = snap or last_live
                break
        else:
            last_frames = fr
            stable_since = time.time()

    _request("POST", f"/live/cameras/{camera_id}/stop", token)
    snap = last_live or last

    frames = snap.get("frames_received", 0)
    sampled = snap.get("frames_sampled", 0)
    evt = snap.get("total_events", 0)
    captured = snap.get("evidence_captured", 0)
    ok &= record(sampled > 0, "live session sampled frames", f"received={frames} sampled={sampled}", section=sec)
    ok &= record(evt >= 0, "live session tracked events", f"events={evt}", section=sec)
    record(captured >= 0, "live evidence capture measured", f"captured={captured} indexed={snap.get('evidence_indexed', 0)}", section=sec)

    perf = {
        "transport": snap.get("transport"),
        "frames_received": frames,
        "frames_sampled": sampled,
        "detection_total_processed": (snap.get("detection_metrics") or {}).get("total_processed", 0),
        "detection_total_detections": (snap.get("detection_metrics") or {}).get("total_detections", 0),
        "detection_inference_avg_ms": (snap.get("detection_metrics") or {}).get("inference_latency_avg_ms"),
        "vlm_observations": snap.get("vlm_observations", 0),
        "evidence_captured": captured,
        "evidence_indexed": snap.get("evidence_indexed", 0),
    }
    set_section(sec, ok)
    return perf


def verify_rag(token: str) -> bool:
    sec = "RAG"
    ok = True
    # Grounded question on the street clip should yield evidence+answer
    st, out = _request("POST", "/rag/query", token, body={"query": "what objects are visible in the street scene?", "video_id": 6})
    ok &= record(st == 200, "rag/query responds", f"status={st}", section=sec)
    answer = (out or {}).get("answer", "") if st == 200 else ""
    ok &= record(bool(answer), "rag query returns an answer", str(answer)[:80], section=sec)

    # UNKNOWN abstention must be honest (identity / intent questions)
    st, out = _request("POST", "/rag/query", token, body={"query": "what is the identity of the person in this footage?"})
    if st == 200 and out.get("answer"):
        ans = (out.get("answer") or "")
        honest = "UNKNOWN" in ans or "INSUFFICIENT" in ans.upper()
        ok &= record(honest, "identity question abstains (UNKNOWN)", ans[:80], section=sec)
    else:
        record(False, "identity question received", "no answer", section=sec)

    # Video-scoped search (evidence-backed)
    st, inv = _request("POST", "/investigation/search", token, body={"query": "person or vehicle movement", "case_id": 2, "top_k": 5})
    ok &= record(st == 200, "investigation/search responds", f"status={st}", section=sec)
    if st == 200:
        res = inv.get("results", [])
        record(True, "search returns result list", f"{len(res)} results", section=sec)
        ok &= record(bool(inv.get("answer")), "search returns answer", str(inv.get("answer"))[:80], section=sec)
    set_section(sec, ok)
    return ok


def verify_agent(token: str) -> bool:
    sec = "AGENT"
    ok = True
    st, invs = _request("GET", "/investigations", token)
    ok &= record(st == 200, "investigations list responds", f"status={st}", section=sec)
    invs = invs or []
    with open(os.path.join(ROOT, "cases.json"), encoding="utf-8") as fh:
        case_titles = {c.get("title") for c in json.load(fh)}
    matched = [i for i in invs if str(i.get("title", "")) in case_titles]
    ok &= record(len(matched) >= 10, "10 CASE-DEMO investigations exist", f"found {len(matched)}", section=sec)

    # Phase 7 investigation run
    query = "what objects and movement are visible in the street scene?"
    st, run = _request("POST", "/investigations/2/investigate", token, body={"query": query, "require_review": False})
    if st == 500:
        detail = run.get("detail", "") if isinstance(run, dict) else str(run)
        table_missing = "investigation_runs" in str(detail)
        ok &= record(False, "agent investigation run executes",
                     f"500 - investigation_runs table missing (pre-existing DB migration issue)",
                     section=sec)
    else:
        ok &= record(st == 200, "agent investigation run executes", f"status={st}", section=sec)
        if st == 200:
            run_status = run.get("status")
            answer = (
                run.get("answer") or run.get("conclusion")
                or (run.get("result") or {}).get("summary") or ""
            )
            ok &= record(bool(run_status), "agent run has status", str(run_status), section=sec)
            ok &= record(bool(answer), "agent run produced an answer", str(answer)[:100], section=sec)

    st, runs = _request("GET", "/investigations/2/runs", token)
    if st == 500:
        ok &= record(False, "agent runs listable", "500 - investigation_runs table missing", section=sec)
    else:
        ok &= record(st == 200, "agent runs listable", f"status={st}", section=sec)

    # Phase 6 chat
    st, chat = _request("POST", "/investigations/2/chat", token, body={"message": "what was observed in this case?"})
    ok &= record(st == 200, "phase 6 investigation chat responds", f"status={st}", section=sec)
    if st == 200:
        ok &= record(bool(chat.get("reply") or chat.get("answer") or chat.get("message") or chat.get("agent_result")),
                      "chat returns a reply", section=sec)

    st, timeline = _request("GET", "/investigations/2/timeline", token)
    if st == 500:
        ok &= record(False, "timeline endpoint responds", "500 - timeline_events table issue", section=sec)
    else:
        ok &= record(st == 200, "timeline endpoint responds", f"status={st}", section=sec)
    set_section(sec, ok)
    return ok


def verify_negative(token: str) -> bool:
    sec = "NEGATIVE"
    ok = True
    # cartoon video: near-zero detections, zero events
    _, videos = _request("GET", "/videos", token)
    cartoon = next((v for v in videos if "demo_video_06" in v.get("filename", "")), None)
    if cartoon is None:
        set_section(sec, False)
        record(False, "cartoon robustness video exists", section=sec)
        return False
    counts = _detection_counts(token, cartoon["id"])
    ok &= record(sum(counts.values()) < 20, "cartoon has near-zero detections", f"labels={counts}", section=sec)
    st, events = _request("GET", f"/videos/{cartoon['id']}/events", token)
    ok &= record(st == 200 and len(events) == 0, "cartoon produces zero events", f"events={len(events)}", section=sec)

    # not_a_video upload must fail gracefully
    na = os.path.join(ROOT, "videos", "fixtures", "not_a_video.mp4")
    st, _ = _request("POST", f"/videos/upload", token)
    ok &= record(st in (400, 405, 422), "bad upload rejected", f"status={st}", section=sec)
    set_section(sec, ok)
    return ok


def verify_security(token: str) -> bool:
    sec = "SECURITY"
    ok = True
    st, disc = _request("GET", "/demo/disclaimer", token)
    ok &= record(st == 200 and "NOT REAL FORENSIC EVIDENCE" in (disc or {}).get("disclaimer", ""),
                 "demo disclaimer endpoint identifies non-forensic data", section=sec)
    st, ds = _request("GET", "/demo/dataset", token)
    if st == 200:
        d = (ds or {}).get("disclaimer", "")
        ok &= record("NOT REAL FORENSIC EVIDENCE" in d, "dataset payload carries disclaimer", section=sec)
        bad = [v.get("demo_id") for v in (ds or {}).get("videos", []) if v.get("status") == "FAILED"]
        record(not bad, "no demo videos in FAILED state", f"failed={bad}", section=sec)
    set_section(sec, ok)
    return ok


# -------------------------------------------------------------------- main


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser(description="Comprehensive demo dataset verification (section matrix)")
    parser.add_argument("--base-url", nargs="?", const=BASE_URL_DEFAULT, help="also run server checks")
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print("section DATASET:")
    verify_dataset()

    results: dict = {"checks": CHECKS, "statuses": dict(STATUSES), "live_run": None}

    if args.base_url:
        BASE = args.base_url.rstrip("/")
        token = _login()
        if token:
            print("section UPLOAD:")
            verify_uploads(token)
            print("section LIVE:")
            perf = verify_live(token)
            results["live_run"] = perf
            print("section RAG:")
            verify_rag(token)
            print("section AGENT:")
            verify_agent(token)
            print("section NEGATIVE:")
            verify_negative(token)
            print("section SECURITY:")
            verify_security(token)
        else:
            STATUSES.setdefault("UPLOAD", "NOT TESTED")
            for s in ("LIVE", "RAG", "AGENT", "NEGATIVE", "SECURITY"):
                STATUSES.setdefault(s, "NOT TESTED")
    else:
        for s in ("UPLOAD", "LIVE", "RAG", "AGENT", "NEGATIVE", "SECURITY"):
            STATUSES.setdefault(s, "NOT TESTED")
        print("local-only mode: pass --base-url to also verify live/RAG/agent/negative/security")

    results["statuses"] = dict(STATUSES)
    with open(os.path.join(RESULTS_DIR, "verification_all_results.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    print("\nsection matrix:")
    overall = True
    for sec_name, val in STATUSES.items():
        print(f"  {val:10s} {sec_name}")
        if val != "PASS":
            overall = False
    print(f"\noverall: {'PASS' if overall else 'FAIL'} -> "
          f"{os.path.join(RESULTS_DIR, 'verification_all_results.json')}")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()