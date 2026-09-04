select distinct facts.product_id
from {{ ref('fct_daily_inventory_movement') }} as facts
left join {{ ref('dim_product') }} as dim
    on facts.product_id = dim.product_id
where dim.product_id is null
