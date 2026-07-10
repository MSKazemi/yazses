-- Force every table to use fixed relative column widths so long cells WRAP
-- inside the page instead of overflowing the right margin in the PDF. Pandoc's
-- LaTeX writer only emits wrapping `p{}` columns when columns have widths; GFM
-- pipe tables usually carry none, so we assign equal widths here.
function Table(tbl)
  local specs = tbl.colspecs
  if specs and #specs > 0 then
    local w = 1.0 / #specs
    for i = 1, #specs do
      -- colspec = {alignment, width}; setting a numeric width → wrapping p{} column
      specs[i][2] = w
    end
  end
  return tbl
end
