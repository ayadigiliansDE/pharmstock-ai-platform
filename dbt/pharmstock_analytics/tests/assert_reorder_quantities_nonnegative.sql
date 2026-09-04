select *
from {{ ref('fct_reorder_events') }}
where available_quantity < 0
   or reorder_point < 0
   or target_stock_level < 0
   or recommended_reorder_quantity < 0
