import { createContext, useContext } from "react";
import clsx from "clsx";

const TabsContext = createContext(null);

export function Tabs({ value, onValueChange, tabs, children }) {
  return (
    <TabsContext.Provider value={value}>
      <div>
        <div role="tablist" className="mb-5 flex gap-6 border-b border-border">
          {tabs.map((tab) => {
            const selected = value === tab.value;
            return (
              <button
                key={tab.value}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => onValueChange(tab.value)}
                className={clsx(
                  "-mb-px border-b-2 px-0.5 pb-3 text-body",
                  selected ? "border-accent font-medium text-ink" : "border-transparent text-ink-secondary",
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
        {children}
      </div>
    </TabsContext.Provider>
  );
}

export function TabPanel({ value, children }) {
  const current = useContext(TabsContext);
  if (current !== value) return null;
  return <div role="tabpanel">{children}</div>;
}
