import os
from . import billing
from .billing import send_invoice as invoice
from pyapp.store import Base, OrderError

DEFAULT_STATUS = "open"


class OrderService(Base):
    """Keeps orders. Acme Robotics is headquartered in Boulder. Priya Natarajan lives in Boulder.

    Second paragraph, not part of the first."""

    __tablename__ = "orders"

    def place(self, order):
        """Place an order: total it with billing, send the invoice and log the path. Acme Robotics ships from Boulder."""
        amount = billing.total(order)
        try: invoice(order)
        except OrderError: raise ValueError("bad order")
        self.log(os.path.join("a", "b"))
        print(amount)
        return amount

    def log(self, msg): return msg

    def list_open(self):
        return self.run("SELECT id, total FROM orders WHERE status = 'open'")

    def save(self, order):
        self.run("INSERT INTO orders (id, total) VALUES (?, ?)")
        raise OrderError("nope")

    def archive(self, order):
        db.archive_orders.insert_one(order)

    def graph(self, order):
        session.run("MATCH (o:Order)-[:PLACED_BY]->(c:Customer) RETURN c")

    def run(self, sql): return sql
