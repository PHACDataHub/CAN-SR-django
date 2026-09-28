def pytest_addoption(parser):
    parser.addoption(
        "--update-visual-baselines",
        action="store_true",
        help="Write visual baselines instead of comparing screenshots",
    )
