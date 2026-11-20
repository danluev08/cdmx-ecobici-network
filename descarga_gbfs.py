# %% [markdown]
# # Descarga del feed GBFS de Ecobici (CDMX)
# Paso 1 del proyecto: bajar station_information y station_status,
# unirlos en una sola tabla de pandas y guardar un snapshot.

# %% [1] Librerías y constantes
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

GBFS_INDEX = "https://gbfs.mex.lyftbikes.com/gbfs/gbfs.json"
CARPETA_DATOS = Path("data")

# %% [2] Leer el índice GBFS y encontrar la URL de cada feed
# El índice no trae datos de estaciones: solo dice dónde está cada feed.
# Las URLs se leen de ahí en vez de escribirlas a mano, para que el script
# siga funcionando aunque el operador las cambie.
resp = requests.get(GBFS_INDEX, timeout=30)
resp.raise_for_status()  # si el servidor responde con error, se detiene aquí
indice = resp.json()

datos = indice["data"]
# En GBFS v2 los feeds vienen agrupados por idioma: data -> {"en": {"feeds": [...]}}
# En GBFS v3 vienen directo: data -> {"feeds": [...]}
if "feeds" in datos:
    feeds = datos["feeds"]
else:
    idioma = next(iter(datos))
    print("Idioma del feed:", idioma)
    feeds = datos[idioma]["feeds"]

urls = {f["name"]: f["url"] for f in feeds}
print("Versión GBFS:", indice.get("version", "no indicada"))
for nombre, url in urls.items():
    print(f"  {nombre:25s} {url}")


# %% [3] Función para bajar un feed y convertirlo en DataFrame
def bajar_feed(nombre: str) -> tuple[pd.DataFrame, datetime]:
    """Descarga un feed GBFS de estaciones y regresa (tabla, hora de actualización)."""
    r = requests.get(urls[nombre], timeout=30)
    r.raise_for_status()
    j = r.json()
    # last_updated es un "timestamp Unix": segundos desde el 1 ene 1970 (UTC)
    hora = datetime.fromtimestamp(j["last_updated"], tz=timezone.utc)
    print(f"{nombre}: actualizado {hora.astimezone():%Y-%m-%d %H:%M:%S} (hora local)")
    return pd.DataFrame(j["data"]["stations"]), hora


info, hora_info = bajar_feed("station_information")
status, hora_status = bajar_feed("station_status")

# En GBFS v3 el nombre viene como lista de traducciones; lo dejamos como texto
if isinstance(info["name"].iloc[0], list):
    info["name"] = info["name"].apply(lambda x: x[0]["text"])

print("\nstation_information:", info.shape, "(renglones, columnas)")
print(list(info.columns))
print("\nstation_status:", status.shape)
print(list(status.columns))

# %% [4] Vistazo rápido a cada tabla
info.head()

# %%
status.head()

# %% [5] Unir las dos tablas por station_id
# info = lo estático (dónde está y cuántos docks tiene) -> los NODOS de la red
# status = lo dinámico (cuántas bicis hay ahorita)
# Usamos how="outer" con indicator=True para ver si hay estaciones que aparecen
# en una tabla y no en la otra, en lugar de perderlas sin darnos cuenta.
cols_info = [c for c in ["station_id", "name", "lat", "lon", "capacity"] if c in info.columns]
cols_status = [
    c
    for c in [
        "station_id",
        "num_bikes_available",
        "num_docks_available",
        "num_bikes_disabled",
        "num_docks_disabled",
        "is_installed",
        "is_renting",
        "is_returning",
        "last_reported",
    ]
    if c in status.columns
]

estaciones = info[cols_info].merge(
    status[cols_status],
    on="station_id",
    how="outer",
    indicator=True,
    validate="one_to_one",  # truena si un station_id viene repetido
)

print("¿De qué tabla viene cada estación?")
print(estaciones["_merge"].value_counts())
# both       = está en las dos (lo normal)
# left_only  = está en info pero no tiene status
# right_only = tiene status pero no sabemos dónde está

# %% [6] Revisión de sanidad antes de analizar nada
print("Estaciones totales:", len(estaciones))
print("Bicis disponibles en todo el sistema:", int(estaciones["num_bikes_available"].sum()))
print("Capacidad total (docks):", int(estaciones["capacity"].sum()))
print("\nValores faltantes por columna:")
print(estaciones.isna().sum())

for col in ["is_installed", "is_renting", "is_returning"]:
    if col in estaciones.columns:
        print(f"\n{col}:")
        print(estaciones[col].value_counts(dropna=False))

# %% [7] Guardar el snapshot con la hora del feed en el nombre
# Cada vez que corras esto queda un archivo nuevo. Más adelante, juntar
# varios snapshots es lo que nos dará una serie de tiempo.
CARPETA_DATOS.mkdir(exist_ok=True)
estaciones["snapshot_utc"] = hora_status
archivo = CARPETA_DATOS / f"snapshot_{hora_status:%Y%m%d_%H%M%S}_utc.csv"
estaciones.drop(columns="_merge").to_csv(archivo, index=False, encoding="utf-8")
print("Guardado en:", archivo.resolve())
