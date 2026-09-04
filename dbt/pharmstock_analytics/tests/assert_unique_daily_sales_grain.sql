select event_date, branch_id, product_id, channel, count(*) as row_count
from {{ ref('fct_daily_sales_demand') }}
group by 1, 2, 3, 4
having count(*) > 1
