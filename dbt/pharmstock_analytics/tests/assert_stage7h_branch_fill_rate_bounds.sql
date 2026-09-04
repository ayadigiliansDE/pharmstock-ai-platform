select *
from {{ ref('mart7h_branch_daily_operations') }}
where fill_rate is not null
  and (fill_rate < 0 or fill_rate > 1)
