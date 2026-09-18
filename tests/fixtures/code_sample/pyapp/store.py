class Base:
    """A tiny base class."""

    def log(self, msg):
        return msg


class OrderError(Exception):
    pass
