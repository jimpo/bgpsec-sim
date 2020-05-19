import click
import networkx as nx
import random
import numpy as np
import tqdm

import as_graph
from as_graph import ASGraph

@click.group()
def cli():
    pass

@cli.command()
@click.argument('as-rel-file')
def check_graph(as_rel_file):
    nx_graph = as_graph.parse_as_rel_file(as_rel_file)

    if not nx.is_connected(nx_graph):
        print("Graph is not fully connected!")
    else:
        print("Graph is fully connected")

    graph = ASGraph(nx_graph)
    print("Checking for customer-provider cycles")
    if graph.any_customer_provider_cycles():
        print("Graph has a customer-provider cycle!")
    else:
        print("Graph has no cycles")
        
@cli.command()
@click.argument('as-rel-file')
@click.argument('as-reachability-file')
# Outputs a list of <ASIN> <# reachable ASes>, 
def check_connectivity(as_rel_file, as_reachability_file):
    (c2p_graph, p2p_graph, p2c_graph) = as_graph.parse_by_rel_type(as_rel_file)
    
    index = {}
    reverse_index = {}

    for i, n in enumerate(p2p_graph.nodes):
        index[n] = i
        reverse_index[i] = n
    
    num_nodes = p2p_graph.number_of_nodes()
    
    print("Loaded", num_nodes, "nodes")
    print("Loaded", c2p_graph.number_of_edges(), "directed edges")
    print("Loaded", p2p_graph.number_of_edges(), "undirected edges")
    
    # Array of nodes reachable by descent into a customer cone
    p2c_adjacency = np.zeros((num_nodes, num_nodes), dtype=np.byte)
    print("Descending into the valley of consumption...")
    for source in tqdm.tqdm(p2c_graph.nodes):
        for destination in nx.bfs_tree(p2c_graph, source):
            p2c_adjacency[index[source]][index[destination]] = 1   
    del p2c_graph

    print("Finding peer-customers...")
    # Array of nodes reachable by one peer-peer edge and descent into a customer cone
    p2pc_adjacency = np.zeros((num_nodes, num_nodes), dtype=np.byte)
    for source in tqdm.tqdm(p2p_graph.nodes):
        si = index[source]  
        for destination in p2p_graph[source]:
            p2pc_adjacency[si] += p2c_adjacency[index[destination]]
    del p2p_graph
    
    print("Climbing the mountain of provision...")    
    reachability = np.zeros((num_nodes, num_nodes), dtype=np.byte)
    for source in tqdm.tqdm(c2p_graph.nodes):
        reachability[index[source]][index[source]] = 1
        
        # Get any nodes reachable by taking customer->provider links
        for destination in nx.bfs_tree(c2p_graph, source):
            [si, di] = index[source], index[destination]
            reachability[si][di] = 1
            # While we're here, let's also get any peers and peer-customers of the destination
            reachability[si] += p2pc_adjacency[di]
        
    reachable_counts = {}
    print("Compiling reachability dictionary...")
    for source in tqdm.tqdm(c2p_graph.nodes):
        reachable_counts[source] = np.count_nonzero(reachability[index[source]])
    
    with open(as_reachability_file, 'w') as file:
        for asin in tqdm.tqdm(c2p_graph.nodes):
            file.write(str(asin) + " " + str(reachable_counts[asin]))

@cli.command()
@click.argument('as-rel-file')
@click.argument('target-asn', type=int)
def figure2a(as_rel_file, target_asn):
    nx_graph = as_graph.parse_as_rel_file(as_rel_file)

    graph = ASGraph(nx_graph)
    print("Loaded graph")

    # origin_id = random.choice(list(graph.asyss.keys()))
    origin_id = int(target_asn)
    origin = graph.get_asys(origin_id)

    # path = nx.shortest_path(nx_graph, 205970, origin_id)

    print(f"Finding routes to AS {origin_id}")
    graph.find_routes_to(origin)

    path_lengths = {}
    for asys in graph.asyss.values():
        if origin_id in asys.routing_table:
            path_len = asys.routing_table[origin.as_id].length
        else:
            # print(f"AS {asys.as_id} has no path to {origin_id}")
            path_len = -1
        if path_len not in path_lengths:
            path_lengths[path_len] = 0
        path_lengths[path_len] += 1
    for path_len, count in sorted(path_lengths.items()):
        print(f"path_length: {path_len}, count: {count}")

@cli.command()
def hello():
    click.echo('Hello world')

if __name__ == '__main__':
    cli()
