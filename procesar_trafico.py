"""
PROCESAR_TRAFICO: Ahora solo existe como referencia histórica.
El sistema usa A* con datos locales (length) sin simulación aleatoria.

Con Just-in-Time: Los pesos de tráfico REAL se obtienen SOLO cuando:
1. El usuario solicita una ruta A→B.
2. A* calcula la ruta local usando 'length'.
3. Se hace 1 ÚNICA llamada a Google Directions API con origen→destino.
4. Se obtiene ETA y distancia REAL con tráfico en vivo.

Nota: Esta función está DEPRECADA. Se mantendrá para referencia.
"""

def inyectar_trafico(G):
    """
    DEPRECADA: Esta función inyectaba datos aleatorios a todas las aristas en startup.
    Con la arquitectura Just-in-Time, esto NO es necesario.
    
    A* usa solo 'length' localmente.
    Las consultas a la API de Google Maps se hacen bajo demanda.
    """
    print(" [DEPRECADA] inyectar_trafico: No se ejecuta en modo Just-in-Time")
    return G
