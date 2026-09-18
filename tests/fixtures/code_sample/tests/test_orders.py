from pyapp.orders import OrderService


def test_place():
    assert OrderService().place({"id": 1, "lines": [1]}) == 1
