from collections import deque
import networkx as nx
from typing import Dict, List, Optional

import error
from asys import AS, AS_ID, Relation
from routing_policy import DefaultPolicy

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

def parse_by_rel_type(filename: str) -> (nx.Graph, nx.Graph, nx.Graph):
    c2p_graph = nx.DiGraph()
    p2p_graph = nx.Graph()
    p2c_graph = nx.DiGraph()

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
            for graph in [c2p_graph, p2p_graph, p2c_graph]:
                if as1 not in graph:
                    graph.add_node(as1)
                if as2 not in graph:
                    graph.add_node(as2)
            
            if rel == 0:
                p2p_graph.add_edge(as1, as2)
            elif rel == -1:
                c2p_graph.add_edge(as2, as1)
                p2c_graph.add_edge(as1, as2)
 
    return (c2p_graph, p2p_graph, p2c_graph)

class ASGraph(object):
    __slots__ = ['asyss', 'graph']

    asyss: Dict[AS_ID, AS]

    def __init__(self, graph: nx.Graph):
        self.asyss = {}
        for as_id in graph.nodes:
            self.asyss[as_id] = AS(as_id, DefaultPolicy())
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
        pass

    def any_customer_provider_cycles(self) -> bool:
        graph = nx.DiGraph()
        for asys in self.asyss.values():
            graph.add_node(asys.as_id)
        for asys in self.asyss.values():
            for neighbor, relation in asys.neighbors.items():
                if relation == Relation.CUSTOMER:
                    graph.add_edge(asys.as_id, neighbor.as_id)
        return not nx.is_directed_acyclic_graph(graph)

    def clear_routing_tables(self):
        for asys in self.asyss:
            asys.clear_routing_table()

    def find_routes_to(self, target: AS):
        routes: deque = deque()
        for neighbor in target.neighbors:
            routes.append(target.originate_route(neighbor))

        while routes:
            route = routes.popleft()
            asys = route.final
            for neighbor in asys.learn_route(route):
                routes.append(asys.forward_route(route, neighbor))

    def hijack_n_hops(self, victim: AS, attacker: AS, n: int):
        pass
