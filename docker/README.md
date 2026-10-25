# Configs internas de Docker

Este directorio contiene configs que se montan dentro de los contenedores Docker
de Langfuse (no las toca el usuario en desarrollo normal).

## `clickhouse-config.xml`

**Qué hace:** Configura ClickHouse para usar el engine `ReplicatedMergeTree` con un cluster
single-node. Langfuse 3 requiere esto para sus migrations de schema
(`CREATE TABLE ... ON CLUSTER`).

**Por qué single-node:** Las migrations de Langfuse usan ReplicatedMergeTree
que asume coordinación distribuida. En dev local con un solo contenedor
ClickHouse, el coordinator es `clickhouse-keeper` (ver abajo).

**No tocar** salvo que migres a un cluster ClickHouse multi-shard de producción.

## `clickhouse-keeper-config.xml`

**Qué hace:** Configura ClickHouse Keeper, el coordinator de ReplicatedMergeTree
(en lugar de ZooKeeper que era el default histórico).

**Puerto:** `2181` (cliente) + `9181` (consensus) + `10181` (interserver) + `44444` (metrics).
Mapeados en docker-compose para comunicación interna entre los contenedores.

**No tocar** salvo que migres a un cluster distribuido.

## ¿Modificar en producción?

Para producción con ClickHouse clusterizado:
1. Cambiar `<replica>` y `<shard>` definitions en `clickhouse-config.xml`
2. Levantar múltiples nodos `clickhouse` y múltiples `clickhouse-keeper`
3. Actualizar `LANGFUSE_INIT_*` env vars para apuntar al cluster

Esto **no es necesario** para dev/staging con un solo nodo.