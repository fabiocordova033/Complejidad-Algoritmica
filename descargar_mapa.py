import osmnx as ox
import networkx as nx
import matplotlib.pyplot as plt
from procesar_trafico import inyectar_trafico  

def descargar_y_analizar_mapa(lugar="Carabayllo, Lima, Peru"):
    print(f"Descargando el grafo de calles para: {lugar}...")

    G = ox.graph_from_place(lugar, network_type='drive')

    print("Inyectando factores de tráfico para calcular pesos...")
    inyectar_trafico(G)

    num_nodos = G.number_of_nodes()
    num_aristas = G.number_of_edges()

    print("-" * 30)
    print("ESTADÍSTICAS DEL GRAFO")
    print(f"Nodos (Intersecciones): {num_nodos}")
    print(f"Aristas (Calles): {num_aristas}")
    print("-" * 30)

    # Guardar el grafo para usarlo en el resto de tu app
    ox.save_graphml(G, filepath="mapa_base.graphml")
    print(" Grafo guardado como 'mapa_base.graphml'")

   
    print("\nGenerando imagen del grafo completo...")
    fig, ax = ox.plot_graph(G, 
              node_size=1.5,          
              node_color="cyan",
              edge_color='red',       
              edge_linewidth=0.5,     
              show=False, 
              close=False, 
              save=False) 
    fig.savefig("grafo_hito1.png", dpi=300, bbox_inches='tight')
    plt.close(fig)
    print("-> Imagen guardada: 'grafo_hito1.png'")

  
    print("\nGenerando subgrafo de detalle con los PESOS en las calles...")
    nodos_lista = list(G.nodes())
    nodo_central = nodos_lista[100] # Nodo de enfoque
    
    # Extraemos el subgrafo a 4 cuadras a la redonda
    subgrafo_barrio = nx.ego_graph(G, nodo_central, radius=4)

    fig2, ax2 = ox.plot_graph(subgrafo_barrio, 
                  node_size=30,          
                  node_color='cyan',     
                  edge_color='red',      
                  edge_linewidth=2,      
                  show=False, 
                  close=False, 
                  save=False)

    # Extraer posiciones (coordenadas x,y) de los nodos para saber dónde poner los números
    pos = {n: (subgrafo_barrio.nodes[n]['x'], subgrafo_barrio.nodes[n]['y']) for n in subgrafo_barrio.nodes()}
    
    # Leer el 'peso_final' que generó tu archivo procesar_trafico.py
    etiquetas_pesos = {}
    for u, v, d in subgrafo_barrio.edges(data=True):
        # Tomamos el peso_final y lo redondeamos a 1 decimal para que no se vea amontonado
        peso = d.get('peso_final', d.get('length', 0))
        etiquetas_pesos[(u, v)] = f"{peso:.1f}"

    # Dibujas los pesos de las aristas
    nx.draw_networkx_edge_labels(subgrafo_barrio, pos, 
                                 edge_labels=etiquetas_pesos, 
                                 ax=ax2, 
                                 font_size=6, 
                                 font_color='black',
                                 bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=0.5))

    fig2.savefig("subgrafo_barrio.png", dpi=300, bbox_inches='tight')
    plt.close(fig2)
    print("-> Imagen guardada: 'subgrafo_barrio.png'")

    print("\n¡Proceso terminado! Ya tienes las 2 imágenes exactas para tu informe de Word.")

if __name__ == "__main__":
    descargar_y_analizar_mapa("Carabayllo, Lima, Peru")