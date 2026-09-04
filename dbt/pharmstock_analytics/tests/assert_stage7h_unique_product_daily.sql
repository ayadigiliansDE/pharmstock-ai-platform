select business_date, product_id, count(*) as row_count
from {{ ref('mart7h_product_daily_performance') }}
group by 1, 2
having count(*) > 1
