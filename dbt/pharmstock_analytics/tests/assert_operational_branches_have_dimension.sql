select distinct facts.branch_id
from {{ ref('mart_branch_daily_operations') }} as facts
left join {{ ref('dim_branch') }} as dim
    on facts.branch_id = dim.branch_id
where dim.branch_id is null
