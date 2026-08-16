"""
RegionSwitcher — swaps the active DSQL endpoint to the peer region.

Used in demo_2 to simulate a full region failure and prove the saga
resumes seamlessly from the peer Aurora DSQL cluster.
"""
import os


class RegionSwitcher:
    def __init__(self):
        self.primary = os.environ.get("DSQL_ENDPOINT", "")
        self.peer = os.environ.get("DSQL_ENDPOINT_PEER", "")

    def fail_over(self) -> str:
        """Switch DSQL_ENDPOINT to the peer region. Returns the new endpoint."""
        if not self.peer:
            raise RuntimeError("DSQL_ENDPOINT_PEER is not set — cannot failover")
        print(f"\n[CHAOS] Simulating region failure.")
        print(f"        Was : {self.primary}")
        print(f"        Now : {self.peer}\n")
        os.environ["DSQL_ENDPOINT"] = self.peer
        return self.peer

    def restore(self) -> str:
        """Restore the primary endpoint."""
        os.environ["DSQL_ENDPOINT"] = self.primary
        return self.primary

    @property
    def active_endpoint(self) -> str:
        return os.environ.get("DSQL_ENDPOINT", self.primary)
