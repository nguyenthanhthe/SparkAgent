"""SparkAgent — single entry point for the 24/7 agent daemon.

Usage:
    python main.py                    start the 24/7 daemon (default)
    python main.py --check            offline self-test (no network, no LLM)
    python main.py --once "goal..."   run a single ReAct episode, then exit
    python main.py --config my.yaml   use a custom config file

Windows note: the Proactor event loop policy is required for subprocess
support (OpenShell) and is set automatically.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

if sys.platform == "win32" and sys.version_info < (3, 14):
    # Proactor is the default loop on Windows; the policy API is deprecated
    # in 3.14, so only pin it on older interpreters.
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sparkagent",
        description="SparkAgent — autonomous 24/7 local AI agent kernel")
    parser.add_argument("--config", default=None,
                        help="path to config.yaml (defaults + env still apply)")
    parser.add_argument("--check", action="store_true",
                        help="run the offline self-test and exit")
    parser.add_argument("--once", metavar="GOAL", default=None,
                        help="run one ReAct episode for GOAL and exit")
    parser.add_argument("--export-policy", metavar="FILE",
                        default=None,
                        help="export the current policy as a draft "
                             "OpenShell sandbox policy and exit")
    parser.add_argument("--version", action="version",
                        version="SparkAgent 0.2.0")
    return parser


def run_check() -> int:
    """Offline validation: config, policy, vault, memory, guards, parsers."""
    from kernel.config import Config
    from kernel.memory import Memory
    from kernel.react import extract_json
    from openshell import SecurityError, SecretVault, SecurityPolicy
    from security.quarantine import MAX_TOTAL_BYTES, QuarantineStore
    from tools.webfetch import BlockedURLError, validate_url
    from pathlib import Path
    import tempfile

    failures: list[str] = []

    def check(name: str, fn) -> None:
        try:
            fn()
            print(f"  ok    {name}")
        except Exception as exc:  # noqa: BLE001
            failures.append(name)
            print(f"  FAIL  {name}: {exc}")

    print("SparkAgent self-check")

    def config_loads():
        cfg = Config.load()
        assert cfg.get("brain.local.model"), "local model missing"
        assert cfg.get("agent.max_steps", 0) > 0
    check("config defaults load", config_loads)

    def policy_blocks_danger():
        sandbox = Path(tempfile.mkdtemp())
        policy = SecurityPolicy(["python"], [sandbox], sandbox)
        for program, args in (
                ("shutdown", []), ("cmd", []),
                ("python", ["-c", "format C: /y"]),
                ("python", ["../../escape.py"])):
            try:
                policy.validate_command(program, args)
                raise AssertionError(f"{program} {args} should be blocked")
            except SecurityError:
                pass
    check("security policy blocks danger", policy_blocks_danger)

    def ssrf_guard_blocks_internal():
        for url in ("http://127.0.0.1/x", "http://169.254.169.254/latest",
                    "http://192.168.0.1/", "file:///etc/passwd"):
            try:
                validate_url(url, {80, 443})
                raise AssertionError(f"{url} should be blocked")
            except BlockedURLError:
                pass
    check("SSRF guard blocks internal targets", ssrf_guard_blocks_internal)

    def vault_crypto_roundtrip():
        import os
        old = os.environ.get("SPARKAGENT_VAULT_KEY")
        os.environ["SPARKAGENT_VAULT_KEY"] = "selftest-key"
        try:
            store = Path(tempfile.mkdtemp()) / "vault.bin"
            vault = SecretVault(store)
            vault.set("SELFTEST", "value-1")
            assert SecretVault(store).get("SELFTEST") == "value-1"
        finally:
            if old is None:
                os.environ.pop("SPARKAGENT_VAULT_KEY", None)
            else:
                os.environ["SPARKAGENT_VAULT_KEY"] = old
    check("vault encrypt/decrypt roundtrip", vault_crypto_roundtrip)

    def memory_roundtrip():
        async def scenario():
            memory = Memory(Path(tempfile.mkdtemp()) / "t.db",
                            embedder_fn=None, embed_dim=128)
            await memory.connect()
            await memory.remember("gpu temperature is high", kind="note")
            hits = await memory.recall("gpu temperature")
            assert hits and "gpu" in hits[0].text.lower()
            await memory.close()
        asyncio.run(scenario())
    check("memory remember/recall", memory_roundtrip)

    def json_extraction():
        assert extract_json('```json\n{"final_answer": "x"}\n```')
        assert extract_json('prose {"thought": "t"} prose')["thought"] == "t"
        assert extract_json("garbage") is None
    check("ReAct JSON extraction", json_extraction)

    def quarantine_and_budget():
        store = QuarantineStore(Path(tempfile.mkdtemp()) / "q")
        store.put("check payload", "selftest")
        stats = store.stats()
        assert stats["items"] == 1 and stats["bytes"] > 0
        store.delete(next(iter(store.list()))["id"])
        assert store.stats()["items"] == 0
        # budget store cap invariant: putting beyond the total cap evicts
        store.put("x" * 1000, "selftest")
        store.put("y" * 1000, "selftest")
        assert store.stats()["bytes"] <= MAX_TOTAL_BYTES
    check("quarantine store + budget sanity", quarantine_and_budget)

    if failures:
        print(f"\n{len(failures)} check(s) FAILED")
        return 1
    print("\nall checks passed")
    return 0


async def run_once(goal: str, config_path: str | None) -> int:
    from kernel.config import Config
    from kernel.daemon import AgentDaemon

    daemon = AgentDaemon(Config.load(config_path))
    # interfaces stay off for one-shot runs; memory + brain are enough
    daemon.cfg._data.setdefault("interface", {})
    daemon.cfg._data["interface"]["web"] = {"enabled": False}
    daemon.cfg._data["interface"]["telegram"] = {"enabled": False}
    await daemon.memory.connect()
    try:
        result = await daemon.run_once(goal, source="operator")
        print(f"\nstatus : {result.status} ({result.steps} steps, "
              f"tier: {result.tier or 'n/a'})")
        print("answer :\n" + (result.answer or "(none)"))
        return 0 if result.status == "done" else 2
    finally:
        await daemon.brain.close()
        await daemon.fetcher.close()
        await daemon.memory.close()


async def run_daemon(config_path: str | None) -> None:
    from kernel.config import Config
    from kernel.daemon import AgentDaemon

    daemon = AgentDaemon(Config.load(config_path))
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    import signal

    def request_stop(*_args) -> None:
        stop.set()

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, request_stop)
            except (NotImplementedError, RuntimeError):
                # Windows: add_signal_handler unsupported for SIGTERM/SIGBREAK
                try:
                    signal.signal(sig, request_stop)
                except (ValueError, OSError):
                    pass

    await daemon.start()
    try:
        await stop.wait()
    except KeyboardInterrupt:
        pass  # handled by the signal hook / asyncio.run
    finally:
        await daemon.stop()


def run_export_policy(output: str, config_path: str | None) -> int:
    from kernel.config import Config
    from kernel.daemon import AgentDaemon
    from openshell.policy_translate import export_policy_file
    from pathlib import Path

    daemon = AgentDaemon(Config.load(config_path))
    document = export_policy_file(daemon.policy, Path(output),
                                  sandbox_name=daemon.cfg.get(
                                      "openshell.sandbox_name",
                                      "sparkagent"))
    print(f"exported draft OpenShell policy -> {output} "
          f"(sandbox: {document['metadata']['name']}, "
          f"programs: {len(document['spec']['process']['execAllowlist'])})")
    print("review and apply via OpenShell's own policy flow; "
          "SparkAgent will not install it")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        return run_check()
    if args.export_policy:
        return run_export_policy(args.export_policy, args.config)
    if args.once:
        return asyncio.run(run_once(args.once, args.config))
    try:
        asyncio.run(run_daemon(args.config))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
