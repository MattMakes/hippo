"""Billing helpers."""


def total(order):
    return sum(order["lines"])


def send_invoice(order):
    print("sending", order["id"])
