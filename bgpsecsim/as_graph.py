from collections import deque
import networkx as nx
import random
from typing import Dict, Generator, List, Optional, Tuple

import bgpsecsim.error as error
from bgpsecsim.asys import AS, AS_ID, Relation, Route, RoutingPolicy
from bgpsecsim.routing_policy import DefaultPolicy

def parse_as_rel_file(filename: str) -> nx.Graph:
    with open(filename, 'r') as f:
        graph = nx.Graph()

        for line in f:
            # Ignore lines starting with #
            if line.startswith('#'):
                continue

            # The 'serial-1' as-rel files contain p2p and p2c relationships. The format is:
            # <provider-as>|<customer-as>|-1
            # <peer-as>|<peer-as>|0
            items = line.split('|')
            if len(items) != 3:
                raise error.InvalidASRelFile(filename, f"bad line: {line}")

            [as1, as2, rel] = map(int, items)
            if as1 not in graph:
                graph.add_node(as1)
            if as2 not in graph:
                graph.add_node(as2)

            customer = as2 if rel == -1 else None
            graph.add_edge(as1, as2, customer=customer)

    return graph

class ASGraph(object):
    __slots__ = ['asyss', 'graph']

    asyss: Dict[AS_ID, AS]

    def __init__(self, graph: nx.Graph, policy: RoutingPolicy = DefaultPolicy()):
        self.asyss = {}
        for as_id in graph.nodes:
            self.asyss[as_id] = AS(as_id, policy)
        for (as_id1, as_id2) in graph.edges:
            as1 = self.asyss[as_id1]
            as2 = self.asyss[as_id2]
            customer = graph.edges[(as_id1, as_id2)]['customer']
            if customer is None:
                as1.add_peer(as2)
                as2.add_peer(as1)
            elif customer == as_id1:
                as1.add_provider(as2)
                as2.add_customer(as1)
            elif customer == as_id2:
                as1.add_customer(as2)
                as2.add_provider(as1)

    def get_asys(self, as_id: AS_ID) -> Optional[AS]:
        return self.asyss.get(as_id, None)

    def identify_top_isps(self, n: int) -> List[AS]:
        """Top ISPs by customer degree."""
        isps = [(asys, asys.neighbor_counts_by_relation())
                for asys in self.asyss.values()]
        isps.sort(key=lambda pair: -pair[1][Relation.CUSTOMER])
        return [asys for asys, _ in isps[:n]]

    def get_providers(self, ids: List[AS_ID]) -> List[AS]:
        """Return providers of a list of ASes, as a set"""
        providers = set([])
        for as_id in ids:
            for p_id in self.asyss[as_id].get_providers():
                providers.add(p_id)
        return list(providers)

    def determine_reachability_one(self, as_id: AS_ID) -> int:
        """Returns how many ASs can the given AS, itself included."""
        graph = self._build_reachability_graph()
        n_ancestors = len([as_id
                           for side, as_id in nx.ancestors(graph, ('r', as_id))
                           if side == 'l'])
        return n_ancestors

    def determine_reachability_all(self) -> Dict[AS_ID, int]:
        """Returns how many ASs can reach each AS, themselves included."""
        graph = self._build_reachability_graph()

        # Process nodes in topological order, keeping track of which ones they are reachable from
        # with a bitfield.
        queue: deque = deque()
        remaining_edges = {}
        for node in graph:
            remaining_edges[node] = graph.in_degree(node)
            if remaining_edges[node] == 0:
                del remaining_edges[node]
                queue.append(node)
        while queue:
            node = queue.popleft()
            for next_node in graph.successors(node):
                graph.nodes[next_node]['reachable_from'] |= graph.nodes[node]['reachable_from']
                remaining_edges[next_node] -= 1
                if remaining_edges[next_node] == 0:
                    del remaining_edges[next_node]
                    queue.append(next_node)

        return { as_id: bit_count(graph.nodes[('r', as_id)]['reachable_from'])
                 for as_id in self.asyss }

    def _build_reachability_graph(self) -> nx.DiGraph:
        graph = nx.DiGraph()
        for asys in self.asyss.values():
            graph.add_node(('l', asys.as_id), reachable_from=(1 << asys.as_id))
            graph.add_node(('r', asys.as_id), reachable_from=0)
            graph.add_edge(('l', asys.as_id), ('r', asys.as_id))
        for asys in self.asyss.values():
            for neighbor, relation in asys.neighbors.items():
                if relation == Relation.CUSTOMER:
                    graph.add_edge(('r', asys.as_id), ('r', neighbor.as_id))
                elif relation == Relation.PEER:
                    graph.add_edge(('l', asys.as_id), ('r', neighbor.as_id))
                elif relation == Relation.PROVIDER:
                    graph.add_edge(('l', asys.as_id), ('l', neighbor.as_id))
        return graph

    def any_customer_provider_cycles(self) -> bool:
        graph = nx.DiGraph()
        for asys in self.asyss.values():
            graph.add_node(asys.as_id)
        for asys in self.asyss.values():
            for neighbor, relation in asys.neighbors.items():
                if relation == Relation.CUSTOMER:
                    graph.add_edge(asys.as_id, neighbor.as_id)
        return not nx.is_directed_acyclic_graph(graph)

    def clear_routing_tables(self) -> None:
        for asys in self.asyss.values():
            asys.reset_routing_table()

    def find_routes_to(self, target: AS) -> None:
        routes: deque = deque()
        for neighbor in target.neighbors:
            routes.append(target.originate_route(neighbor))

        while routes:
            route = routes.popleft()
            asys = route.final
            for neighbor in asys.learn_route(route):
                routes.append(asys.forward_route(route, neighbor))

    def hijack_n_hops(self, victim: AS, attacker: AS, n: int) -> None:
        if n < 0:
            raise ValueError("number of hops must be non-negative")
        elif n == 0:
            path = [attacker]
        elif n == 1:
            path = [victim, attacker]
        else:
            asyss = list(set(self.asyss.values()) - set([victim, attacker]))
            middle = random.sample(asyss, n - 1)
            path = [victim] + middle + [attacker]

        bad_route = Route(
            victim.as_id,
            path,
            origin_invalid=n == 0,
            path_end_invalid=n <= 1,
            authenticated=False
        )

        routes: deque = deque()
        for neighbor in attacker.neighbors:
            routes.append(attacker.forward_route(bad_route, neighbor))

        while routes:
            route = routes.popleft()
            asys = route.final
            for neighbor in asys.learn_route(route):
                routes.append(asys.forward_route(route, neighbor))

def bit_count(bitfield: int) -> int:
    return bin(bitfield).count('1')

def asyss_by_customer_count(
        graph: nx.Graph,
        min_count: int,
        max_count: Optional[int]
) -> Generator[int, None, None]:
    for node in graph:
        customer_count = sum((1
                             for neighbor in graph[node]
                             if graph[node][neighbor]['customer'] == neighbor))
        if min_count <= customer_count and (max_count is None or max_count >= customer_count):
            yield node
