-- One candidate's attempt: build its feature table and record its score, both on this branch.
-- Every attempt runs this; only the parameters differ.
CALL ds_build('{features}', '{model}', {score})
