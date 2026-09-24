from app.sandbox.ports import PortRegistry


def test_allocate_and_release_port():
    registry = PortRegistry()
    port = registry.allocate(45000, 45100)
    assert port in registry.reserved()
    assert not registry.is_available(port)
    registry.release(port)
    assert port not in registry.reserved()
