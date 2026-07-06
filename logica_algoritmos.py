import networkx as nx

class MotorAlgoritmos:
    """
    Motor de cálculo de rutas basado en OSMnx.
    NOTA: En la arquitectura actual (Just-in-Time):
    - OSMnx solo encuentra el nodo más cercano
    - Google Directions API calcula la ruta real con tráfico
    - Los puntos exactos del mapa vienen de Google, no de OSMnx
    """
    
    def __init__(self, G):
        """Inicializa el motor con un grafo dirigido de OSMnx"""
        self.G = G
        self.nodos = list(G.nodes())
    
    def calcular_ruta_mas_corta(self, nodo_origen, nodo_destino, peso='length'):
        """
        Calcula la ruta más corta usando Dijkstra (NetworkX).
        DIJKSTRA: Busca el camino mínimo basado en peso (distancia física).
        
        Args:
            nodo_origen: nodo inicial
            nodo_destino: nodo final
            peso: atributo de arista a usar como distancia (default: 'length')
        
        Returns:
            Lista de nodos [n1, n2, n3, ...] o None si no existe ruta
        """
        try:
            # nx.shortest_path usa Dijkstra por defecto
            ruta = nx.shortest_path(self.G, nodo_origen, nodo_destino, weight=peso)
            return ruta
        except nx.NetworkXNoPath:
            print(f" No existe ruta entre {nodo_origen} y {nodo_destino}")
            return None
        except nx.NodeNotFound:
            print(f" Nodo no encontrado en el grafo")
            return None
        except Exception as e:
            print(f" Error calculando ruta: {e}")
            return None

    def calcular_ruta_con_trafico(self, nodo_origen, nodo_destino):
        """
        Calcula la ruta usando Dijkstra incorporando un factor de tráfico aleatorio
        en las aristas para simular condiciones variables de congestión de forma dinámica.
        """
        import random
        try:
            def peso_trafico(u, v, d):
                longitud = d.get('length', 1.0)
                # Multiplicador de tráfico aleatorio entre 1.0 (libre) y 2.5 (embotellamiento severo)
                factor_trafico = random.uniform(1.0, 2.5)
                return longitud * factor_trafico

            ruta = nx.shortest_path(self.G, nodo_origen, nodo_destino, weight=peso_trafico)
            
            distancia_m = 0
            for i in range(len(ruta) - 1):
                u, v = ruta[i], ruta[i+1]
                edge_data = self.G.get_edge_data(u, v)
                if edge_data:
                    if isinstance(edge_data, dict) and 0 in edge_data:
                        distancia_m += edge_data[0].get('length', 0)
                    elif isinstance(edge_data, dict):
                        distancia_m += edge_data.get('length', 0)
            
            return ruta, distancia_m
        except Exception as e:
            print(f"Error en Dijkstra con tráfico dinámico: {e}")
            return None, 0