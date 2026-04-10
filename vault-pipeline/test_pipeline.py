#!/usr/bin/env python3
"""
test_pipeline.py — Run a PDF through every pipeline stage and report results.

Usage:
    python3 test_pipeline.py <path-to-pdf>            # local file upload
    python3 test_pipeline.py --url <pdf-url>          # URL-based ingest
    python3 test_pipeline.py --slug <existing-slug>   # resume from existing slug

Options:
    --base  http://localhost:5004   vault-pipeline base URL (default)
    --skip-cloud                    skip LlamaCloud stages (classify/extract/akn)
    --skip-embed                    skip LightRAG embed (slow)
    --log   pipeline_test.log       also write output to this file

Example:
    python3 test_pipeline.py sample.pdf
    python3 test_pipeline.py sample.pdf --skip-cloud --skip-embed
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

# ── Colours ───────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✓{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET} {msg}")
def err(msg):  print(f"  {RED}✗{RESET} {msg}")
def info(msg): print(f"  {CYAN}·{RESET} {msg}")
def header(msg): print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}\n{BOLD}{msg}{RESET}")


class PipelineTest:
    def __init__(self, base_url: str, log_file: str | None = None):
        self.base = base_url.rstrip("/")
        self.client = httpx.Client(timeout=300.0)
        self.slug: str = ""
        self.results: list[dict] = []
        self.log_path = log_file
        self.log_lines: list[str] = []

    def _log(self, line: str):
        self.log_lines.append(line)

    def _call(self, method: str, path: str, **kwargs) -> tuple[bool, dict]:
        url = f"{self.base}{path}"
        t0 = time.perf_counter()
        try:
            resp = self.client.request(method, url, **kwargs)
            elapsed = time.perf_counter() - t0
            try:
                data = resp.json()
            except Exception:
                data = {"_raw": resp.text[:500]}
            success = resp.status_code < 400 and data.get("success", True) is not False
            return success, data, elapsed
        except Exception as e:
            elapsed = time.perf_counter() - t0
            return False, {"error": str(e)}, elapsed

    def run_stage(self, label: str, method: str, path: str, skip: bool = False, **kwargs) -> dict:
        header(f"Stage: {label}")
        self._log(f"\n{'='*60}\nStage: {label}\n{'='*60}")

        if skip:
            warn(f"SKIPPED")
            self._log("SKIPPED")
            self.results.append({"stage": label, "status": "skipped", "elapsed": 0})
            return {}

        success, data, elapsed = self._call(method, path, **kwargs)
        status = "ok" if success else "error"

        if success:
            ok(f"elapsed={elapsed:.1f}s")
        else:
            err(f"FAILED  elapsed={elapsed:.1f}s")

        # Print key fields from response
        skip_keys = {"success", "message", "slug", "meta", "stages"}
        for k, v in data.items():
            if k in skip_keys:
                continue
            if isinstance(v, (dict, list)) and len(str(v)) > 120:
                info(f"{k}: [truncated — {len(v) if isinstance(v, list) else len(str(v))} items]")
            else:
                info(f"{k}: {v}")

        if data.get("message"):
            info(f"message: {data['message']}")
        if data.get("error"):
            err(f"error: {data['error']}")

        log_entry = f"elapsed={elapsed:.2f}s  status={status}\n{json.dumps(data, indent=2, default=str)}"
        self._log(log_entry)
        self.results.append({"stage": label, "status": status, "elapsed": elapsed, "data": data})
        return data

    def upload_pdf(self, pdf_path: str) -> str:
        header("Upload PDF")
        path = Path(pdf_path)
        if not path.exists():
            err(f"File not found: {pdf_path}")
            sys.exit(1)

        info(f"file={path.name}  size={path.stat().st_size/1024:.1f} KB")
        with open(path, "rb") as f:
            success, data, elapsed = self._call(
                "POST", "/vault/save-pdf-upload",
                files={"file": (path.name, f, "application/pdf")},
            )

        if not success:
            err(f"Upload failed: {data}")
            sys.exit(1)

        slug = data.get("slug", "")
        ok(f"slug={slug}  elapsed={elapsed:.1f}s")
        self._log(f"upload: slug={slug}  elapsed={elapsed:.2f}s")
        return slug

    def ingest_url(self, url: str) -> str:
        header("Ingest PDF via URL")
        info(f"url={url}")
        success, data, elapsed = self._call(
            "POST", "/vault/ingest-pdf",
            json={"url": url},
        )
        if not success:
            err(f"Ingest failed: {data}")
            sys.exit(1)
        slug = data.get("slug", "")
        ok(f"slug={slug}  elapsed={elapsed:.1f}s")
        self._log(f"ingest_url: slug={slug}  elapsed={elapsed:.2f}s")
        return slug

    def save_log(self):
        if not self.log_path:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header_txt = f"Pipeline Test Log — {ts}\nSlug: {self.slug}\n{'='*60}\n"
        with open(self.log_path, "w") as f:
            f.write(header_txt + "\n".join(self.log_lines))
        print(f"\n{CYAN}Log saved → {self.log_path}{RESET}")

    def summary(self):
        header("Test Summary")
        total = len(self.results)
        passed = sum(1 for r in self.results if r["status"] == "ok")
        skipped = sum(1 for r in self.results if r["status"] == "skipped")
        failed = sum(1 for r in self.results if r["status"] == "error")
        total_time = sum(r["elapsed"] for r in self.results)

        print(f"\n  Slug:    {BOLD}{self.slug}{RESET}")
        print(f"  Stages:  {total}  ({GREEN}passed={passed}{RESET}  {YELLOW}skipped={skipped}{RESET}  {RED}failed={failed}{RESET})")
        print(f"  Time:    {total_time:.1f}s total\n")

        for r in self.results:
            icon = {"ok": f"{GREEN}✓{RESET}", "skipped": f"{YELLOW}−{RESET}", "error": f"{RED}✗{RESET}"}[r["status"]]
            print(f"  {icon}  {r['stage']:<30} {r['elapsed']:.1f}s")

        self._log(f"\nSUMMARY: passed={passed} skipped={skipped} failed={failed} total_time={total_time:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="Test vault-pipeline end-to-end")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("pdf", nargs="?", help="Path to local PDF file")
    group.add_argument("--url", help="PDF URL to ingest")
    group.add_argument("--slug", help="Existing slug (resume from stage_parse)")
    parser.add_argument("--base", default="http://localhost:5004", help="Pipeline base URL")
    parser.add_argument("--skip-cloud", action="store_true", help="Skip LlamaCloud stages (classify/extract/akn)")
    parser.add_argument("--skip-embed", action="store_true", help="Skip LightRAG embed (slow)")
    parser.add_argument("--log", default="pipeline_test.log", help="Log output file")
    args = parser.parse_args()

    t = PipelineTest(args.base, log_file=args.log)

    print(f"\n{BOLD}vault-pipeline end-to-end test{RESET}")
    print(f"  base={args.base}  skip_cloud={args.skip_cloud}  skip_embed={args.skip_embed}")
    print(f"  timestamp={datetime.now().isoformat()}")

    # ── Step 0: health check ───────────────────────────────────
    header("Health Check")
    ok_health, health_data, _ = t._call("GET", "/health")
    if ok_health:
        ok("vault-pipeline is up")
    else:
        err("vault-pipeline not reachable — is Docker running?")
        sys.exit(1)

    # ── Step 1: get slug ───────────────────────────────────────
    if args.slug:
        t.slug = args.slug
        print(f"\n{BOLD}Resuming with existing slug: {t.slug}{RESET}")
    elif args.url:
        t.slug = t.ingest_url(args.url)
    elif args.pdf:
        t.slug = t.upload_pdf(args.pdf)
    else:
        err("Provide a PDF path, --url, or --slug")
        parser.print_help()
        sys.exit(1)

    slug = t.slug
    sr = {"slug": slug}

    # ── Stage: assess ─────────────────────────────────────────
    t.run_stage("assess", "POST", "/vault/stage/assess", json=sr)

    # ── Stage: parse ──────────────────────────────────────────
    t.run_stage("parse", "POST", "/vault/stage/parse", json=sr)

    # ── Stage: cleanse ────────────────────────────────────────
    t.run_stage("cleanse", "POST", "/vault/stage/cleanse", json=sr)

    # ── Stage: classify ───────────────────────────────────────
    t.run_stage("classify", "POST", "/vault/stage/classify",
                skip=args.skip_cloud, json=sr)

    # ── Stage: extract ────────────────────────────────────────
    t.run_stage("extract", "POST", "/vault/stage/extract",
                skip=args.skip_cloud, json=sr)

    # ── Stage: akn ────────────────────────────────────────────
    t.run_stage("akn", "POST", "/vault/stage/akn",
                skip=args.skip_cloud, json=sr)

    # ── Stage: extract_multipass ──────────────────────────────
    t.run_stage("extract_multipass", "POST", "/vault/stage/extract_multipass",
                skip=args.skip_cloud, json=sr)

    # ── Stage: link ───────────────────────────────────────────
    t.run_stage("link", "POST", "/vault/stage/link", json=sr)

    # ── Stage: index ──────────────────────────────────────────
    t.run_stage("index", "POST", "/vault/stage/index", json=sr)

    # ── Stage: enrich ─────────────────────────────────────────
    t.run_stage("enrich", "POST", "/vault/stage/enrich", json=sr)

    # ── Stage: enrich_mca ─────────────────────────────────────
    t.run_stage("enrich_mca", "POST", "/vault/stage/enrich_mca", json=sr)

    # ── Stage: structure ──────────────────────────────────────
    t.run_stage("structure", "POST", "/vault/stage/structure", json=sr)

    # ── Stage: chunk ──────────────────────────────────────────
    t.run_stage("chunk", "POST", "/vault/stage/chunk", json=sr)

    # ── Stage: embed ──────────────────────────────────────────
    t.run_stage("embed", "POST", "/vault/stage/embed",
                skip=args.skip_embed, json=sr)

    # ── Stage: karpathy ───────────────────────────────────────
    t.run_stage("karpathy", "POST", "/vault/stage/karpathy", json=sr)

    # ── Stage: canvas ─────────────────────────────────────────
    t.run_stage("canvas", "POST", "/vault/stage/canvas", json=sr)

    # ── Stage: dashboard ──────────────────────────────────────
    t.run_stage("dashboard", "POST", "/vault/stage/dashboard", json=sr)

    # ── Global: index ─────────────────────────────────────────
    t.run_stage("global/index", "POST", "/vault/global/index",
                json={"force": False})

    # ── Global: matter_group ──────────────────────────────────
    t.run_stage("global/matter_group", "POST", "/vault/global/matter_group")

    # ── Global: entity_resolve ────────────────────────────────
    t.run_stage("global/entity_resolve", "POST", "/vault/global/entity_resolve")

    # ── Global: precedent_graph ───────────────────────────────
    t.run_stage("global/precedent_graph", "POST", "/vault/global/precedent_graph")

    # ── Audit ─────────────────────────────────────────────────
    t.run_stage("audit", "GET", f"/vault/audit?slug={slug}")

    # ── Summary ───────────────────────────────────────────────
    t.summary()
    t.save_log()


if __name__ == "__main__":
    main()
