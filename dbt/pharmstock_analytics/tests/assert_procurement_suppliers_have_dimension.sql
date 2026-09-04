select distinct facts.supplier_id
from {{ ref('fct_procurement_order_lifecycle') }} as facts
left join {{ ref('dim_supplier') }} as dim
    on facts.supplier_id = dim.supplier_id
where dim.supplier_id is null
