import abc
from enum import Enum
from typing import Dict, List, Optional

AS_ID = int

class Relation(Enum):
    CUSTOMER = 1
    PEER = 2
    PROVIDER = 3

class AS(object):
    __slots__ = [
        'as_id', 'neighbors', 'policy', 'publishes_rpki', 'publishes_path_end', 'bgp_sec_enabled',
        'routing_table'
    ]

    as_id: AS_ID
    neighbors: Dict['AS', Relation]
    policy: 'RoutingPolicy'
    publishes_rpki: bool
    publishes_path_end: bool
    bgp_sec_enabled: bool
    routing_table: Dict[AS_ID, 'Route']

    def __init__(
        self,
        as_id: AS_ID,
        policy: 'RoutingPolicy',
        publishes_rpki: bool = False,
        publishes_path_end: bool = False,
        bgp_sec_enabled: bool = False
    ):
        self.as_id = as_id
        self.policy = policy
        self.neighbors = {}
        self.publishes_rpki = publishes_rpki
        self.publishes_path_end = publishes_path_end
        self.bgp_sec_enabled = bgp_sec_enabled
        self.routing_table = {}
        self.reset_routing_table()

    def neighbor_counts_by_relation(self) -> Dict[Relation, int]:
        counts = { relation: 0 for relation in Relation }
        for relation in self.neighbors.values():
            counts[relation] += 1
        return counts
        
    def get_providers(self) -> List[AS_ID]:
        providers = filter(lambda id: self.neighbors[id] == Relation.PROVIDER, self.neighbors.keys())
        return [p.as_id for p in providers]
        
    def add_peer(self, asys: 'AS') -> None:
        self.neighbors[asys] = Relation.PEER

    def add_customer(self, asys: 'AS') -> None:
        self.neighbors[asys] = Relation.CUSTOMER

    def add_provider(self, asys: 'AS') -> None:
        self.neighbors[asys] = Relation.PROVIDER

    def get_relation(self, asys: 'AS') -> Optional[Relation]:
        return self.neighbors.get(asys, None)

    def get_route(self, as_id: AS_ID) -> Optional['Route']:
        return self.routing_table.get(as_id, None)

    def force_route(self, route: 'Route') -> None:
        self.routing_table[route.dest] = route

    def learn_route(self, route: 'Route') -> List['AS']:
        """Learn about a new route.

        Returns a list of ASs to advertise route to.
        """
        if route.dest == self.as_id:
            return []

        if not self.policy.accept_route(route):
            return []

        if (route.dest in self.routing_table and
            not self.policy.prefer_route(self.routing_table[route.dest], route)):
            return []

        self.routing_table[route.dest] = route

        forward_to_relations = set((relation
                                    for relation in Relation
                                    if self.policy.forward_to(route, relation)))

        return [neighbor
                for neighbor, relation in self.neighbors.items()
                if relation in forward_to_relations]

    def originate_route(self, next_hop: 'AS') -> 'Route':
        return Route(
            dest=self.as_id,
            path=[self, next_hop],
            origin_invalid=False,
            path_end_invalid=False,
            authenticated=self.bgp_sec_enabled,
        )

    def forward_route(self, route: 'Route', next_hop: 'AS') -> 'Route':
        return Route(
            dest=route.dest,
            path=route.path + [next_hop],
            origin_invalid=route.origin_invalid,
            path_end_invalid=route.path_end_invalid,
            authenticated=route.authenticated and next_hop.bgp_sec_enabled,
        )

    def reset_routing_table(self) -> None:
        self.routing_table.clear()
        self.routing_table[self.as_id] = Route(
            self.as_id,
            [self],
            origin_invalid=False,
            path_end_invalid=False,
            authenticated=True,
        )

class Route(object):
    __slots__ = ['dest', 'path', 'origin_invalid', 'path_end_invalid', 'authenticated']

    # Destination is an IP block that is owned by this AS. The AS_ID is the same as the origin's ID
    # for valid routes, but may differ in a hijacking attack.
    dest: AS_ID
    path: List[AS]
    # Whether the origin has no valid RPKI record and one is expected.
    origin_invalid: bool
    # Whether the first hop has no valid path-end record and one is expected.
    path_end_invalid: bool
    # Whether the path is authenticated with BGPsec.
    authenticated: bool

    def __init__(
        self,
        dest: AS_ID,
        path: List[AS],
        origin_invalid: bool,
        path_end_invalid: bool,
        authenticated: bool,
    ):
        self.dest = dest
        self.path = path
        self.origin_invalid = origin_invalid
        self.path_end_invalid = path_end_invalid
        self.authenticated = authenticated

    @property
    def length(self) -> int:
        return len(self.path)

    @property
    def origin(self) -> AS:
        return self.path[0]

    @property
    def first_hop(self) -> AS:
        return self.path[-2]

    @property
    def final(self) -> AS:
        return self.path[-1]

    def contains_cycle(self) -> bool:
        return len(self.path) != len(set(self.path))

    def __str__(self) -> str:
        return ','.join((str(asys.as_id) for asys in self.path))

    def __repr__(self) -> str:
        s = str(self)
        flags = []
        if self.origin_invalid:
            flags.append('origin_invalid')
        if self.path_end_invalid:
            flags.append('path_end_invalid')
        if self.authenticated:
            flags.append('authenticated')
        if flags:
            s += " " + " ".join(flags)
        return s

class RoutingPolicy(abc.ABC):
    @abc.abstractmethod
    def accept_route(self, route: Route) -> bool:
        pass

    @abc.abstractmethod
    def prefer_route(self, current: Route, new: Route) -> bool:
        pass

    @abc.abstractmethod
    def forward_to(self, route: Route, relation: Relation) -> bool:
        pass
