select event_date, branch_id, product_id, count(*) as row_count
from {{ ref('fct_daily_inventory_movement') }}
group by 1, 2, 3
having count(*) > 1
