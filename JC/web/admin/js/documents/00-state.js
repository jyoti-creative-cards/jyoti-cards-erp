/** Setup — S3 Documents browser */
const Documents = (() => {
  let ctx = {};
  let currentPrefix = "JCC/";
  let lastData = { folders: [], files: [] };
  let searchQ = "";
  let renameKey = null;

