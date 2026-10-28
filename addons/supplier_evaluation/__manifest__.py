{
    "name": "Supplier Evaluation",
    "version": "18.0.1.0.0",
    "summary": "Puntualitat immutable i historial de terminis dels proveïdors",
    "description": "Consulta l'historial de terminis i confirma renegociacions amb justificació, conservant el compromís original i les avaluacions de recepcions completades.",
    "category": "Inventory/Inventory",
    "license": "LGPL-3",
    "depends": ["base", "purchase", "stock", "purchase_stock"],
    "data": [
        "security/ir.model.access.csv",
        "security/supplier_deadline_security.xml",
        "wizard/deadline_renegotiation_views.xml",
        "views/deadline_views.xml",
        "views/purchase_order_views.xml",
    ],
    "installable": True,
    "application": False,
}
