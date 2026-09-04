select branch.branch_id
from {{ ref('stg_master_branch') }} as branch
left join {{ ref('stg_master_organization') }} as org
    on branch.organization_id = org.organization_id
where org.organization_id is null
