select event_date, product_id, count(*) as row_count
from {{ ref('mart_product_daily_demand') }}
group by 1, 2
having count(*) > 1
