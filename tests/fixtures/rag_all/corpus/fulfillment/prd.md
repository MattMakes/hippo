# Allocation PRD

AC-A [accepted]: Reserve stock only in the requested warehouse.

AC-B [draft]: Substitute stock across warehouses automatically.

AC-Z [superseded]: Global SKU uniqueness is sufficient.

## Decision review

| Decision | State | Rationale |
| --- | --- | --- |
| Availability review 0 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 1 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 2 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 3 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 4 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 5 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 6 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 7 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 8 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 9 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 10 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| Availability review 11 | context | Concurrent reservations must retain the warehouse selected by the caller; retry the transaction against that exact warehouse and product. |
| DEC-W | accepted | Warehouse-scoped reservations prevent promising inventory held at another location. |
