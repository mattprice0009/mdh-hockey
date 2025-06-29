const csv = `
06pyk,ELC1
06cdp,ELC3
066om,ELC2
`.trim();

csv.split('\n').forEach(row => {
  const [id, displayText] = row.trim().split(',');

  // Click the TD
  const td = document.getElementById(`td_${id}`);
  if (td) {
    td.click();
    console.log(`Clicked td_${id}`);
  } else {
    console.warn(`td_${id} not found`);
  }

  // Set the select value by matching option text
  const select = document.getElementById(`con__${id}`);
  if (select) {
    const matchingOption = Array.from(select.options).find(
      option => option.text.trim() === displayText.trim()
    );

    if (matchingOption) {
      select.value = matchingOption.value;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      console.log(`Set con__${id} to option with text "${displayText}" and value "${matchingOption.value}"`);
    } else {
      console.warn(`No matching option with text "${displayText}" found in con__${id}`);
    }
  } else {
    console.warn(`con__${id} not found`);
  }
});