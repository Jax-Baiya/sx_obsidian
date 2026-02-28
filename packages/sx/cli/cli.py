import sys


def interactive_menu(manager, args):
    print("\n🚀 SX Media Control - Interactive Mode")
    print("---------------------------------------")

    profiles = manager.list_profiles()
    print("Available Profiles:")
    for i, p in enumerate(profiles):
        class MockArgs:
            def __init__(self, p):
                self.profile = p
                self.set = []

        tmp_conf = manager.resolve_config(MockArgs(p))
        csv_info = f"({len(tmp_conf['csv_consolidated'])} CSVs)" if tmp_conf["csv_consolidated"] else "(No CSVs)"
        style = tmp_conf.get("path_style", "linux").upper()
        print(f"  [{i+1}] {p:12} -> {tmp_conf['vault']} [{style}] {csv_info}")
    print("  [+] Create New Profile")

    choice = input(f"\nSelect Profile (1-{len(profiles)} or +): ")

    if choice == "+":
        name = input("Enter new profile name: ").strip().lower()
        vault = input("Enter vault absolute path (Linux style): ").strip()
        style = input("Select Path Style (windows|wsl|linux|mac) [linux]: ").strip().lower() or "linux"
        vault_windows = None
        if style == "windows":
            vault_windows = input("Enter Windows vault root (e.g. T:\\AlexNova): ").strip()

        csv1 = input("Enter main consolidated CSV path: ").strip()
        manager.add_profile(name, vault, csv1, path_style=style, vault_windows=vault_windows)
        args.profile = name
    else:
        idx = int(choice) - 1 if choice.isdigit() and 0 < int(choice) <= len(profiles) else 0
        args.profile = profiles[idx]

    print(f"\nSelected Profile: {args.profile.upper()}")
    print("Actions:")
    print("  [1] Sync (Create/Update)")
    print("  [2] Validate (Read-only check)")
    print("  [3] Dry Run (Preview Sync)")
    print("  [4] Soft Cleanup (Delete MD files only)")
    print("  [5] Tidy Run (Cleanup + Sync)")
    print("  [6] Exit")

    act = input("\nAction (1-6) [1]: ")
    if act == "2":
        args.validate = True
        args.mode = None
    elif act == "3":
        args.mode = "sync"
        args.dry_run = True
    elif act == "4":
        args.cleanup = "soft"
        args.mode = None
    elif act == "5":
        args.cleanup = "soft"
        args.mode = "sync"
    elif act == "6":
        sys.exit(0)
    else:
        args.mode = "sync"
        args.cleanup = None
