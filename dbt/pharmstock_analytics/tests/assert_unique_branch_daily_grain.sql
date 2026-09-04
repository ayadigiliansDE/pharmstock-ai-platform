select event_date, branch_id, count(*) as row_count
from {{ ref('mart_branch_daily_operations') }}
group by 1, 2
having count(*) > 1
