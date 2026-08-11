def test_main_module_imports() -> None:
    from app import main

    assert callable(main.main)
