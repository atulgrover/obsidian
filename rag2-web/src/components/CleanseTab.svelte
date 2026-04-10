<script lang="ts">
  import { vault } from '../api/vault';

  let { slug = '' } = $props();

  type TreeNode = {
    id: string;
    level: number;
    title?: string;
    summary?: string;
    pageStart?: number;
    pageEnd?: number;
    depth?: number;
    children?: TreeNode[];
    metadata?: Record<string, any>;
  };

  type FlatTreeNode = TreeNode & {
    depth: number;
  };

  type TreeData = {
    tree?: TreeNode;
  };

  let treeData: TreeData | null = $state(null);
  let loading = $state(false);
  let error = $state('');
  let expanded: Set<string> = $state(new Set());

  $effect(() => { if (slug) loadTree(); });

  async function loadTree() {
    loading = true;
    error = '';
    try {
      treeData = await vault.getTree(slug);
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function toggle(id: string) {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id); else next.add(id);
    expanded = next;
  }

  // Flatten tree into a list for rendering (no recursion in template)
  function flattenTree(node: TreeNode | null | undefined, depth: number = 0): FlatTreeNode[] {
    if (!node) return [];
    const items: FlatTreeNode[] = [];
    for (const child of (node.children || [])) {
      items.push({ ...child, depth });
      if (expanded.has(child.id) && child.children && child.children.length > 0) {
        items.push(...flattenTree(child, depth + 1));
      }
    }
    return items;
  }

  function countNodes(node: TreeNode | null | undefined): number {
    if (!node) return 0;
    return 1 + (node.children || []).reduce((n: number, c: TreeNode) => n + countNodes(c), 0);
  }

  function getTree(): TreeNode | null {
    return treeData?.tree || null;
  }

  function getItems(): FlatTreeNode[] {
    const tree = getTree();
    return tree ? flattenTree(tree) : [];
  }
</script>

<div class="cleanse-tab">
  {#if loading}
    <div class="loading">Loading tree data...</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else if !treeData}
    <div class="empty">No tree data. Run Cleanse first.</div>
  {:else}
    <div class="meta-bar">
      <span class="chip">Nodes: {countNodes(getTree())}</span>
      <span class="chip">Sections: {(getTree()?.children || []).length}</span>
    </div>

    <div class="content">
      {#each getItems() as item}
        <div class="tree-node" style="padding-left: {item.depth * 20 + 8}px">
          <button class="node-row" onclick={() => toggle(item.id)}>
            {#if item.children && item.children.length > 0}
              <span class="toggle">{expanded.has(item.id) ? '▼' : '▶'}</span>
            {:else}
              <span class="toggle leaf">●</span>
            {/if}
            <span class="level-badge">L{item.level}</span>
            <span class="node-title">{item.title || 'Untitled'}</span>
            <span class="node-pages">p.{item.pageStart}–{item.pageEnd}</span>
            <span class="node-words">{item.metadata?.wordCount || 0}w</span>
            {#if item.metadata?.type === 'content'}
              <span class="type-badge leaf-type">leaf</span>
            {:else}
              <span class="type-badge section-type">section</span>
            {/if}
          </button>
          {#if expanded.has(item.id) && item.summary}
            <div class="node-summary" style="padding-left: {item.depth * 20 + 40}px">{item.summary}</div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .cleanse-tab { display: flex; flex-direction: column; height: 100%; }
  .meta-bar { display: flex; gap: 6px; padding: 8px 16px; border-bottom: 1px solid #312e81; }
  .chip { background: #1e1b4b; border: 1px solid #312e81; border-radius: 4px; padding: 2px 8px; font-size: 11px; color: #818cf8; }

  .content { flex: 1; overflow-y: auto; padding: 8px 0; }

  .node-row {
    display: flex; align-items: center; gap: 6px; padding: 4px 8px; cursor: pointer;
    font-size: 12px; color: #c4b5fd; background: none; border: none; width: 100%; text-align: left;
  }
  .node-row:hover { background: rgba(79, 70, 229, 0.1); }
  .toggle { width: 14px; font-size: 10px; color: #818cf8; }
  .toggle.leaf { color: #22c55e; font-size: 8px; }
  .level-badge { background: #312e81; padding: 1px 4px; border-radius: 3px; font-size: 10px; color: #a78bfa; }
  .node-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .node-pages { color: #6b7280; font-size: 10px; }
  .node-words { color: #6b7280; font-size: 10px; }
  .type-badge { font-size: 9px; padding: 1px 4px; border-radius: 3px; }
  .leaf-type { background: #1e3a1e; color: #22c55e; }
  .section-type { background: #1e1b4b; color: #818cf8; }

  .node-summary { font-size: 11px; color: #818cf8; padding: 2px 8px 6px; font-style: italic; }

  .loading, .error, .empty { padding: 32px; text-align: center; color: #818cf8; }
  .error { color: #ef4444; }
</style>
