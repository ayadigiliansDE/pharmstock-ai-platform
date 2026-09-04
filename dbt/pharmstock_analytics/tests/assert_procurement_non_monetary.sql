select *
from {{ ref('fct_procurement_order_lifecycle') }}
where monetary_values_generated
