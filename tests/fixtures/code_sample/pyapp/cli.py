from pyapp import OrderService


def main():
    service = OrderService()
    service.place({"id": 1, "lines": [1]})
