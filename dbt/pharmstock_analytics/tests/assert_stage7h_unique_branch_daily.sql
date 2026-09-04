select business_date, branch_id, count(*) as row_count
from {{ ref('mart7h_branch_daily_operations') }}
group by 1, 2
having count(*) > 1
