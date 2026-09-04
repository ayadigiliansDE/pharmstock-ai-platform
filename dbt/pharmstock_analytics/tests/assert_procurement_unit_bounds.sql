select *
from {{ ref('fct_procurement_order_lifecycle') }}
where ordered_units < 0
   or received_units < 0
   or restocked_units < 0
   or receipt_fill_rate < 0
