# Fuentes y diagramas por patrón

Revisado el 2026-10-10. Cada URL listada aquí y en `data/patterns/*.yaml` se
abrió y se comparó con su título (autores, año y venue). Volver a abrirlas
antes de la demo: los sitios cambian (la guía de MLOps de Google pasó de
`cloud.google.com` a `docs.cloud.google.com` y la URL vieja daba 404).

## Cómo se usan

- **Fuentes** (`fuentes:` en cada YAML → columna `architect_patterns.fuentes`,
  migración 0019): aparecen como enlaces bajo cada cita en `CitationList`. No
  entran a los embeddings (`build_pattern_chunks` no las usa), así que agregar
  fuentes no cambia el retrieval ni el golden set (#108).
- **Plantillas de diagrama** (`app/core/diagram_templates.py`): en el turno de
  diagrama, si hay propuesta aprobada, se detecta su patrón principal y se
  agrega al prompt **solo** esa plantilla. Ninguna plantilla incluye
  observabilidad, gateway, broker ni nodos de despliegue por defecto.

Después de migrar (0019) hay que volver a correr `scripts/seed_patterns.py`,
igual que con la 0018, para que las fuentes nuevas lleguen a la base.

## Literatura transversal para decidir

| Referencia | Para qué sirve |
| --- | --- |
| [ATAM: Method for Architecture Evaluation (Kazman, Klein y Clements, SEI 2000)](https://www.sei.cmu.edu/library/atam-method-for-architecture-evaluation) | Método para evaluar trade-offs entre atributos de calidad; base para la tabla de trade-offs. |
| [How do architecture patterns and tactics interact? (Harrison y Avgeriou, JSS 2010)](https://research.rug.nl/en/publications/how-do-architecture-patterns-and-tactics-interact-a-model-and-ann/) | Cómo cada patrón facilita o dificulta tácticas de calidad. |
| [An Introduction to Software Architecture (Garlan y Shaw, 1994)](https://apps.dtic.mil/sti/tr/pdf/ADA288356.pdf) | Definición clásica de estilos: pipes and filters, capas, invocación implícita (eventos). |
| [Some Initial Performance Characteristics of Three Architectural Styles (Grahn y Bosch, WOSP 1998)](https://hgr.cse.bth.se/Papers/wosp98.pdf) | Mide rendimiento de pipes and filters, capas y blackboard. |
| [The trade-offs between Monolithic vs. Distributed Architectures (Felisberto, 2024)](https://arxiv.org/abs/2405.03619) | Revisión de cuándo conviene monolito o distribuido según costo y complejidad. |

## Diagrama de referencia por patrón

La plantilla resume la figura canónica de la fuente indicada.

| Patrón | Forma de la plantilla | Diagrama de referencia |
| --- | --- | --- |
| Capas | Cliente → Presentación → Aplicación → Datos → BD, sin saltos | [Azure N-tier](https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/n-tier); Garlan y Shaw §3.4 |
| Hexagonal | Adaptadores de entrada → núcleo (puertos, casos de uso) → adaptadores de salida | [Cockburn](https://alistair.cockburn.us/hexagonal-architecture/); [AWS](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/hexagonal-architecture.html) |
| Clean Architecture | Círculos concéntricos, dependencias hacia adentro | [Martin 2012](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html); [Microsoft Learn, fig. 5-7/5-8](https://learn.microsoft.com/en-us/dotnet/architecture/modern-web-apps-azure/common-web-application-architectures) |
| Monolito modular | Un despliegue, módulos con interfaz pública, una BD | [Shopify 2019](https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity); [Su y Li 2024](https://arxiv.org/abs/2401.11867) |
| Microservicios | Cliente → (gateway opcional) → servicios, cada uno con su BD | [Azure Microservices](https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/microservices) |
| API Gateway + BFF | Un BFF por tipo de cliente | [Azure BFF](https://learn.microsoft.com/en-us/azure/architecture/patterns/backends-for-frontends); [Sam Newman](https://samnewman.io/patterns/architectural/bff/) |
| Orientada a eventos | Productores → broker → consumidores (asíncrono) | [Azure EDA](https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/event-driven) |
| CQRS | Camino de comandos y camino de consultas, proyección entre modelos | [Azure CQRS](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs) |
| Event sourcing | Comando → agregado → almacén de eventos → proyecciones | [Azure Event Sourcing](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing) |
| Saga | Orquestador → pasos locales, cada uno con compensación | [Azure Saga](https://learn.microsoft.com/en-us/azure/architecture/patterns/saga); [microservices.io](https://microservices.io/patterns/data/saga.html) |
| Serverless | Entrada HTTP gestionada → funciones → servicios gestionados | [Roberts, martinfowler.com 2018](https://martinfowler.com/articles/serverless.html) |
| SOA | Consumidores → capa de integración (ESB) → servicios → sistemas existentes | [AWS SOA](https://aws.amazon.com/what-is/service-oriented-architecture/) |
| Microkernel | Núcleo + contrato de extensión + plugins | [Richards, cap. 3](https://www.oreilly.com/library/view/software-architecture-patterns/9781491971437/ch03.html) |
| MVC / MVVM | Vista → controlador/viewmodel → modelo; notificación a la vista | [Krasner y Pope 1988](https://ics.uci.edu/~dfredmil/ics227-SQ04/papers/KrasnerPope88.pdf); [Microsoft MVVM](https://learn.microsoft.com/en-us/dotnet/architecture/maui/mvvm) |
| Pipes and Filters | Fuente → filtros en orden → destino | [Azure Pipes and Filters](https://learn.microsoft.com/en-us/azure/architecture/patterns/pipes-and-filters); Garlan y Shaw §3.1 |
| ETL / ELT | Fuentes → extracción → staging → transformación → carga → BI, con orquestador | [Azure ETL](https://learn.microsoft.com/en-us/azure/architecture/data-guide/relational-data/etl) |
| Lambda / Kappa | Kappa: log → streaming → servicio; Lambda: batch + velocidad → servicio | [Azure Big data architectures](https://learn.microsoft.com/en-us/azure/architecture/databases/guide/big-data-architectures) |
| Medallion | Bronce → plata → oro → consumo | [Databricks](https://www.databricks.com/glossary/medallion-architecture) |
| MLOps | Datos → entrenamiento → registro → serving → monitoreo | [Google Cloud MLOps](https://docs.cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning); [Kreuzberger et al. 2022](https://arxiv.org/abs/2205.02302) |

## Fuentes académicas agregadas (por patrón)

- **Capas**: Garlan y Shaw 1994; Grahn y Bosch 1998 (además de Belle et al. y Ameller et al. que ya estaban).
- **Microservicios**: Dragoni et al. 2017; Soldani et al., JSS 2018; Taibi et al., CLOSER 2018; Fritzsch et al. 2019.
- **Monolito modular**: Su y Li 2024; Felisberto 2024; Johnson et al. 2024 (Service Weaver).
- **Orientada a eventos**: Garlan y Shaw 1994 (invocación implícita).
- **CQRS**: Fowler 2011 (advertencia de uso); Overeem et al., JSS 2021; Lytvynov y Hruzin 2025 (apoyo a la decisión entre variantes).
- **Event sourcing**: Overeem et al., JSS 2021; Lytvynov y Hruzin 2025.
- **Saga**: Garcia-Molina y Salem, SIGMOD 1987 (artículo original).
- **Hexagonal**: Nunkesser, ICSOFT 2022.
- **Clean Architecture**: Microsoft Learn; Arias-Orezano et al., TecnoLógicas 2021 (caso cuasi-experimental, evidencia limitada).
- **Serverless**: Jonas et al. 2019 (Berkeley); Eismann et al., IEEE Software 2020; Scheuner y Leitner 2020.
- **API Gateway + BFF**: Taibi et al. 2018; Montesi y Weber 2016; Zimmermann et al. 2020 (Microservice API Patterns).
- **ETL / ELT**: Vassiliadis, IJDWM 2009; Armbrust et al., CIDR 2021.
- **Lambda / Kappa**: Kreps 2014; Kiran et al., IEEE Big Data 2015.
- **Medallion**: Armbrust et al., CIDR 2021; Salami 2025.
- **Microkernel**: Syeed et al., ECSA 2015; Ameller et al., SPE 2013.
- **MLOps**: Kreuzberger et al. 2022; Sculley et al., NeurIPS 2015.
- **MVC / MVVM**: Krasner y Pope, JOOP 1988.
- **Pipes and Filters**: Garlan y Shaw 1994; Philipps y Rumpe, FM 1999; Grahn y Bosch 1998.
- **SOA**: Papazoglou y van den Heuvel, VLDB Journal 2007.

Nota: Wiley (`onlinelibrary.wiley.com`) y ScienceDirect bloquean la lectura
automática; esas dos referencias se confirmaron por sus registros abiertos
(UPCommons y el repositorio de la Universidad de Groningen).
