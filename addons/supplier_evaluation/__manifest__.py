{
    "name": "Supplier Evaluation",
    "version": "18.0.1.3.0",
    "summary": "Completed-line OTD and supplier deadline history",
    "description": "Immutable completed-line OTD based on the latest confirmed agreement or original commitment, with a 24-hour tolerance. Preserves historical receipt snapshots.",
    "category": "Inventory/Inventory",
    "license": "LGPL-3",
    "depends": ["base", "purchase", "stock", "purchase_stock"],
    "data": [
        "security/ir.model.access.csv",
        "security/supplier_deadline_security.xml",
        "wizard/deadline_renegotiation_views.xml",
        "views/deadline_views.xml",
        "views/purchase_order_views.xml",
        "views/res_partner_views.xml",
        "views/supplier_otd_views.xml",
    ],
    "assets": {
        "web.assets_backend": ["supplier_evaluation/static/src/scss/supplier_otd.scss"],
    },
    "installable": True,
    "application": False,
}
